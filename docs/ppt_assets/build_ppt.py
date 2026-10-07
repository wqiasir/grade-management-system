# -*- coding: utf-8 -*-
"""生成《学生成绩管理系统》R2 进度总结 PPT（含出场动画）。

用法：
    python docs/ppt_assets/build_ppt.py

产物：
    PPT/第1次/软件工程课程实践_进度总结_R1-R2.pptx
    （工作目录根下的 PPT 目录按"第 N 次"分次存放，本次汇报产出的 R1~R2 材料归入 第1次）

技术要点：
    python-pptx 本身不提供动画 API，本脚本直接向每页的 ``<p:timing>`` 节点写入
    DrawingML 动画树（``p:par / p:cTn[@presetClass="entr"]``），每加一个形状就
    登记一次动画，天然得到"按出现顺序逐条播放"的出场动画。
"""

from __future__ import annotations

import copy
import os
from typing import Iterable, Sequence

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "out")
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
#: 成品存放目录：工作目录根下的 PPT/第<PPT_ROUND>次/（本次汇报为第 1 次，内容为 R1~R2）
PPT_ROUND = os.environ.get("PPT_ROUND", "1")
PPT_DIR = os.path.join(ROOT, "PPT", f"第{PPT_ROUND}次")
os.makedirs(PPT_DIR, exist_ok=True)

#: 动画播放模式：
#:   "click" —— 每个元素单击一次出现（PowerPoint 默认的出场方式，默认用这个）
#:   "auto"  —— 元素自动依次出现，幻灯片全屏放映时无人值守也能放完
MODE = os.environ.get("PPT_ANIM_MODE", "click")
AUTO_DELAY = 350          # 自动模式下两个效果之间的间隔（毫秒）
EFFECT_DUR = 500          # 单个出场效果的持续时间（毫秒）

OUTPUT = os.path.join(
    PPT_DIR,
    "软件工程课程实践_进度总结_R1-R2.pptx" if MODE == "click"
    else "软件工程课程实践_进度总结_R1-R2_自动播放版.pptx",
)

# --------------------------------------------------------------------------- #
# 设计变量
# --------------------------------------------------------------------------- #
SW, SH = 13.333, 7.5
M = 0.55                    # 左右页边距
CW = SW - 2 * M             # 内容宽度 12.233
CONTENT_TOP = 1.80
CONTENT_H = 4.60
FOOTER_Y = 6.52

NAVY = RGBColor(0x14, 0x2A, 0x52)
INK = RGBColor(0x1B, 0x25, 0x33)
BODY = RGBColor(0x44, 0x4F, 0x5E)
MUTED = RGBColor(0x8A, 0x94, 0xA3)
BLUE = RGBColor(0x1D, 0x4E, 0xD8)
BLUE_L = RGBColor(0xE8, 0xEF, 0xFC)
SKY = RGBColor(0x60, 0xA5, 0xFA)
GREEN = RGBColor(0x0F, 0x76, 0x6E)
GREEN_L = RGBColor(0xE6, 0xF4, 0xF1)
GREEN_B = RGBColor(0x0E, 0x9F, 0x6E)
AMBER = RGBColor(0xB4, 0x53, 0x09)
AMBER_L = RGBColor(0xFD, 0xF3, 0xE3)
PURPLE = RGBColor(0x6D, 0x28, 0xD9)
PURPLE_L = RGBColor(0xF1, 0xEC, 0xFD)
PINK = RGBColor(0x9D, 0x17, 0x4D)
PINK_L = RGBColor(0xFD, 0xEC, 0xF2)
CARD = RGBColor(0xF7, 0xF9, 0xFC)
CARD_B = RGBColor(0xDD, 0xE4, 0xEF)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT = RGBColor(0xC7, 0xD2, 0xE6)

CN = "微软雅黑"
MONO = "Consolas"

FADE, WIPE, FLOAT = "fade", "wipe", "float"

# 动画预设：presetID / presetSubtype / filter
PRESETS = {
    FADE: (10, 0, "fade"),
    WIPE: (22, 4, "wipe(left)"),
    FLOAT: (42, 8, "fade"),  # 浮入：下方浮起
}

# --------------------------------------------------------------------------- #
# 动画（DrawingML timing）工具
# --------------------------------------------------------------------------- #
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
P = f"{{{P_NS}}}"


def _sub(parent, tag: str, **attrs) -> etree._Element:
    el = etree.SubElement(parent, P + tag)
    for k, v in attrs.items():
        el.set(k, str(v))
    return el


def _set_visibility(tn_lst, sid: int, base: int) -> int:
    """形状从隐藏变为可见：p:set + p:to(visible)。"""
    st = _sub(tn_lst, "set")
    cb = _sub(st, "cBhvr")
    ctn = _sub(cb, "cTn", id=base, dur="1", fill="hold")
    stc = _sub(ctn, "stCondLst")
    _sub(stc, "cond", delay="0")
    tgt = _sub(cb, "tgtEl")
    _sub(tgt, "spTgt", spid=sid)
    anl = _sub(cb, "attrNameLst")
    _sub(anl, "attrName").text = "style.visibility"
    to = _sub(st, "to")
    _sub(to, "strVal", val="visible")
    return base + 1


def build_effect_node(tn_lst, sid: int, preset: str, node_type: str, dur: int, nid: int) -> int:
    """写一个效果节点（PowerPoint 的第三层 par/cTn）。

    ``<p:par><p:cTn id=.. presetID=.. presetClass="entr" .. nodeType=..>
       <p:stCondLst><p:cond delay="0"/></p:stCondLst>
       <p:childTnLst>  set + animEffect(+anim)  </p:childTnLst>
    </p:cTn></p:par>``
    """
    pid, subtype, filt = PRESETS[preset]
    par = _sub(tn_lst, "par")
    e = _sub(par, "cTn", id=nid, presetID=pid, presetClass="entr", presetSubtype=subtype,
             fill="hold", grpId="0", nodeType=node_type)
    nid += 1
    stl = _sub(e, "stCondLst")
    _sub(stl, "cond", delay="0")
    inner = _sub(e, "childTnLst")
    nid = _set_visibility(inner, sid, nid)

    ae = _sub(inner, "animEffect", transition="in", filter=filt)
    cb = _sub(ae, "cBhvr")
    _sub(cb, "cTn", id=nid, dur=dur)
    nid += 1
    tgt = _sub(cb, "tgtEl")
    _sub(tgt, "spTgt", spid=sid)

    if preset == FLOAT:
        anim = _sub(inner, "anim", calcmode="lin", valueType="num")
        acb = _sub(anim, "cBhvr")
        actn = _sub(acb, "cTn", id=nid, dur=dur)
        nid += 1
        astc = _sub(actn, "stCondLst")
        _sub(astc, "cond", delay="0")
        atgt = _sub(acb, "tgtEl")
        _sub(atgt, "spTgt", spid=sid)
        aal = _sub(acb, "attrNameLst")
        _sub(aal, "attrName").text = "ppt_y"
        tav = _sub(anim, "tavLst")
        _sub(tav, "tav", tm="0", val="0.05")
        _sub(tav, "tav", tm="100000", val="0")
    return nid


class SlideAnim:
    """收集一页的出场动画，``flush()`` 时一次性写进 ``<p:timing>``。

    结构严格照抄 PowerPoint 自己导出的 timing（用 COM 生成参考文件核对过）：
    ``tmRoot > seq(concurrent=1, nextAc=seek, 无 prevAc) > mainSeq > [外层 par > 中间 par > 效果 par]``。

    两个踩过的坑：
    1. **``p:seq`` 上不能写 ``prevAc``** —— 写了 PowerPoint 直接拒绝打开文件（0x80070010）；
    2. **必须三层 ``p:par`` 嵌套** —— 少一层 PowerPoint 会把 set 与 animEffect 当成两个动画，
       数量翻倍且偶数项读 TriggerType 报错。

    播放节奏用"单击点（beat）"控制：一个 beat 里的多个元素在同一次点击中一起出现
    （第一个是 ``clickEffect``，其余是 ``withEffect``），控制点击次数 ≈ beat 数。
    """

    def __init__(self, slide) -> None:
        self.slide = slide
        #: 每个元素：(sid, preset, 是否 beat 的起点, beat 序号)
        self.items: list[tuple[int, str, bool, int]] = []
        self.beat_index = 0

    def add(self, shape, preset: str = FADE, delay: int = 0, trigger: bool = True) -> None:
        """把形状加进当前 beat（``trigger=True`` 时开启一个新 beat）。"""
        if trigger:
            self.beat_index += 1
        self.items.append((shape.shape_id, preset, trigger, self.beat_index))

    def beat(self, *shapes) -> None:
        """便捷写法：把若干形状放进同一个 beat，第一个开新 beat。"""
        for i, (shape, preset) in enumerate(shapes):
            self.add(shape, preset, trigger=(i == 0))

    def flush(self) -> None:
        if not self.items:
            return
        sld = self.slide._element
        timing = etree.SubElement(sld, P + "timing")
        tn = _sub(timing, "tnLst")
        root_par = _sub(tn, "par")
        root = _sub(root_par, "cTn", id=1, dur="indefinite", restart="never",
                    nodeType="tmRoot")
        c1 = _sub(root, "childTnLst")
        # 关键：不写 prevAc！
        seq = _sub(c1, "seq", concurrent="1", nextAc="seek")
        main = _sub(seq, "cTn", id=2, dur="indefinite", nodeType="mainSeq")
        main_child = _sub(main, "childTnLst")

        nid = 3
        auto_elapsed = 0
        for i, (sid, preset, is_beat_start, beat) in enumerate(self.items):
            prev = self.items[i - 1] if i else None
            same_beat = bool(prev) and not is_beat_start and prev[3] == beat
            if MODE == "auto":
                node_type = "afterEffect"
                delay = auto_elapsed
                auto_elapsed += EFFECT_DUR + AUTO_DELAY
            elif same_beat:
                node_type = "withEffect"
                delay = 0
            else:
                node_type = "clickEffect"
                delay = "indefinite"

            # 第一层：分组。同一 beat 的元素共享一个外层组
            if not same_beat:
                outer = _sub(main_child, "par")
                octn = _sub(outer, "cTn", id=nid, fill="hold")
                nid += 1
                ost = _sub(octn, "stCondLst")
                _sub(ost, "cond", delay=delay)
                och = _sub(octn, "childTnLst")
            # 第二层：把"设置可见性 + 效果"绑成一个动画单元（少了会让数量翻倍）
            mpar = _sub(och, "par")
            mctn = _sub(mpar, "cTn", id=nid, fill="hold")
            nid += 1
            mst = _sub(mctn, "stCondLst")
            _sub(mst, "cond", delay="0")
            mch = _sub(mctn, "childTnLst")
            # 第三层：效果本体
            nid = build_effect_node(mch, sid, preset, {
                "clickEffect": "clickEffect",
                "withEffect": "withEffect",
                "afterEffect": "afterEffect",
            }[node_type], EFFECT_DUR, nid)

        # seq 的前进/后退条件
        prev = _sub(seq, "prevCondLst")
        pc = _sub(prev, "cond", evt="onPrev", delay="0")
        _sub(pc, "tgtEl")
        pc.find(P + "tgtEl").append(etree.SubElement(pc.find(P + "tgtEl"), P + "sldTgt"))
        nxt = _sub(seq, "nextCondLst")
        nc = _sub(nxt, "cond", evt="onNext", delay="0")
        nte = _sub(nc, "tgtEl")
        etree.SubElement(nte, P + "sldTgt")

        # 构建列表：告诉 PowerPoint 这些形状是"按对象"动画的
        bld = _sub(timing, "bldLst")
        for sid, _preset, _start, _beat in self.items:
            _sub(bld, "bldP", spid=sid, grpId="0")

        if MODE == "auto":
            self._add_transition()

    def _add_transition(self, dur: int = 500) -> None:
        """自动播放版追加淡入换片（p:transition 必须排在 p:timing 之前）。"""
        sld = self.slide._element
        tr = etree.Element(P + "transition")
        tr.set("spd", "med")
        tr.set("advClick", "0")
        etree.SubElement(tr, P + "fade")
        timing = sld.find(P + "timing")
        timing.addprevious(tr)


# --------------------------------------------------------------------------- #
# 内容辅助函数
# --------------------------------------------------------------------------- #
def line_of(p, text: str, size: float, bold: bool, color: RGBColor, space_after: float = 0,
            mono: bool = False, align=PP_ALIGN.LEFT, italic: bool = False):
    p.alignment = align
    p.space_after = Pt(space_after)
    run = p.add_run()
    run.text = text
    font = run.font
    font.size = Pt(size)
    font.bold = bold
    font.italic = italic
    font.color.rgb = color
    font.name = MONO if mono else CN
    rpr = run._r.get_or_add_rPr()
    for tag in ("a:latin", "a:ea", "a:cs"):
        el = rpr.find(qn(tag))
        if el is None:
            el = etree.SubElement(rpr, qn(tag))
        el.set("typeface", MONO if mono else CN)
    return run


def lines(shape, lines: Sequence[dict]):
    """往形状里写多行文本。每个元素形如 {t, s, b, c, sa, mono, al, it}。"""
    tf = shape.text_frame
    tf.word_wrap = True
    first = True
    for spec in lines:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        line_of(
            p,
            spec["t"],
            spec.get("s", 13),
            spec.get("b", False),
            spec.get("c", BODY),
            spec.get("sa", 0),
            spec.get("mono", False),
            spec.get("al", PP_ALIGN.LEFT),
            spec.get("it", False),
        )
    return shape


def no_props(shape):
    shape.fill.background()
    shape.line.fill.background()
    shape.shadow.inherit = False
    return shape


# --------------------------------------------------------------------------- #
# Deck
# --------------------------------------------------------------------------- #
class Deck:
    def __init__(self) -> None:
        self.prs = Presentation()
        self.prs.slide_width = Inches(SW)
        self.prs.slide_height = Inches(SH)
        self.page = 0

    # ---------- 基础 ----------
    def note(self, slide, text: str) -> None:
        """演讲者备注（放映时按“演讲者视图”可见）。"""
        slide.notes_slide.notes_text_frame.text = text

    def new(self, section: str, title: str, subtitle: str = "") -> tuple:
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        anim = SlideAnim(slide)
        self.page += 1

        stripe = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(M), Inches(0.6),
                                        Inches(0.075), Inches(0.28))
        stripe.fill.solid()
        stripe.fill.fore_color.rgb = BLUE
        stripe.line.fill.background()
        stripe.shadow.inherit = False
        anim.add(stripe, FADE)

        if section:
            s = slide.shapes.add_textbox(Inches(M + 0.18), Inches(0.56), Inches(6), Inches(0.32))
            no_props(s)
            lines(s, [{"t": section, "s": 12, "b": True, "c": BLUE}])
            anim.add(s, FADE)

        t = slide.shapes.add_textbox(Inches(M), Inches(0.94), Inches(CW), Inches(0.5))
        no_props(t)
        lines(t, [{"t": title, "s": 25, "b": True, "c": INK}])
        anim.add(t, WIPE)

        if subtitle:
            st = slide.shapes.add_textbox(Inches(M), Inches(1.48), Inches(CW), Inches(0.28))
            no_props(st)
            lines(st, [{"t": subtitle, "s": 12.5, "c": MUTED}])
            anim.add(st, FADE)

        self.footer(slide, anim)
        return slide, anim

    def footer(self, slide, anim) -> None:
        f = slide.shapes.add_textbox(Inches(M), Inches(FOOTER_Y), Inches(7), Inches(0.3))
        no_props(f)
        lines(f, [{"t": "学生成绩管理系统 · 软件工程课程实践 · 汇报人：项目组",
                   "s": 10, "c": MUTED}])
        p = slide.shapes.add_textbox(Inches(SW - 1.4), Inches(FOOTER_Y), Inches(0.85), Inches(0.3))
        no_props(p)
        lines(p, [{"t": f"{self.page:02d}", "s": 10.5, "b": True, "c": LIGHT,
                   "al": PP_ALIGN.RIGHT}])

    # ---------- 组件 ----------
    @staticmethod
    def group(anim, *pairs) -> None:
        """把若干 (形状, 效果) 放进同一个"单击点"：第一次点击时它们一起出现。

        用法：``Deck.group(anim, (card, FLOAT), (title, WIPE), (body, FADE))``
        """
        for i, (shape, preset) in enumerate(pairs):
            anim.add(shape, preset, trigger=(i == 0))

    def rect(self, slide, x, y, w, h, fill=None, border=None, radius=None, shape=MSO_SHAPE.ROUNDED_RECTANGLE):
        sh = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
        if fill is None:
            sh.fill.background()
        else:
            sh.fill.solid()
            sh.fill.fore_color.rgb = fill
        if border is None:
            sh.line.fill.background()
        else:
            sh.line.color.rgb = border
            sh.line.width = Pt(0.9)
        sh.shadow.inherit = False
        if radius is not None and shape == MSO_SHAPE.ROUNDED_RECTANGLE:
            sh.adjustments[0] = radius
        return sh

    def box(self, slide, x, y, w, h, specs, anchor=MSO_ANCHOR.TOP, margins=(0.14, 0.14, 0.1, 0.1)):
        sh = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        no_props(sh)
        tf = sh.text_frame
        tf.vertical_anchor = anchor
        l, r, t, b = margins
        tf.margin_left, tf.margin_right = Inches(l), Inches(r)
        tf.margin_top, tf.margin_bottom = Inches(t), Inches(b)
        lines(sh, specs)
        return sh

    def card(self, slide, x, y, w, h, fill=CARD, border=CARD_B, radius=0.06):
        return self.rect(slide, x, y, w, h, fill=fill, border=border, radius=radius)

    def chip(self, slide, x, y, w, h, text, fill=BLUE_L, color=BLUE, size=11.5):
        sh = self.rect(slide, x, y, w, h, fill=fill, radius=0.5)
        tf = sh.text_frame
        tf.word_wrap = False
        tf.margin_left = tf.margin_right = Inches(0.04)
        tf.margin_top = tf.margin_bottom = 0
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        lines(sh, [{"t": text, "s": size, "b": True, "c": color, "al": PP_ALIGN.CENTER}])
        return sh

    def picture(self, slide, name, x, y, width=None, height=None):
        path = os.path.join(ASSETS, name)
        kw = {}
        if width:
            kw["width"] = Inches(width)
        if height:
            kw["height"] = Inches(height)
        return slide.shapes.add_picture(path, Inches(x), Inches(y), **kw)

    def picture_fit(self, slide, name, x, y, w, h, center=True):
        """把图片等比缩放进 w x h 的盒子，返回 (shape, 实际宽, 实际高)。"""
        from PIL import Image

        iw, ih = Image.open(os.path.join(ASSETS, name)).size
        scale = min(w / iw, h / ih)
        pw, ph = iw * scale, ih * scale
        px = x + (w - pw) / 2 if center else x
        py = y + (h - ph) / 2 if center else y
        return self.picture(slide, name, px, py, width=pw), pw, ph

    def arrow(self, slide, x, y, w, h=0.16, color=None):
        sh = slide.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, Inches(x), Inches(y),
                                    Inches(w), Inches(h))
        sh.fill.solid()
        sh.fill.fore_color.rgb = color or LIGHT
        sh.line.fill.background()
        sh.shadow.inherit = False
        return sh

    def connector(self, slide, kind, x1, y1, x2, y2, label=None, color=None, dash=False):
        cn = slide.shapes.add_connector(kind, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
        cn.line.color.rgb = color or SKY
        cn.line.width = Pt(1.3)
        ln = cn.line._get_or_add_ln()
        if dash:
            d = etree.SubElement(ln, qn("a:prstDash"))
            d.set("val", "sysDash")
        head = etree.SubElement(ln, qn("a:tailEnd"))
        head.set("type", "triangle")
        head.set("w", "med")
        head.set("len", "med")
        if label:
            lx = (x1 + x2) / 2
            ly = (y1 + y2) / 2 - 0.14
            self.box(slide, lx - 0.34, ly, 0.68, 0.24,
                     [{"t": label, "s": 9.5, "b": True, "c": BLUE, "al": PP_ALIGN.CENTER}])
        return cn

    # ---------- 页面 ----------
    def cover(self) -> None:
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        anim = SlideAnim(slide)
        self.page = 1

        bg = self.rect(slide, 0, 0, SW, SH, fill=NAVY, shape=MSO_SHAPE.RECTANGLE)
        anim.add(bg, FADE)
        deco = self.rect(slide, 8.55, -1.9, 6.6, 6.6, fill=RGBColor(0x1B, 0x37, 0x6B),
                         shape=MSO_SHAPE.OVAL)
        anim.add(deco, FADE)
        deco2 = self.rect(slide, 10.4, 3.4, 4.6, 4.6, fill=RGBColor(0x17, 0x2F, 0x5D),
                          shape=MSO_SHAPE.OVAL)
        anim.add(deco2, FADE)

        bar = self.rect(slide, M, 1.42, 0.09, 0.62, fill=SKY, shape=MSO_SHAPE.RECTANGLE)
        anim.add(bar, WIPE)
        kicker = self.box(slide, M + 0.22, 1.32, 8, 0.4,
                          [{"t": "软件工程课程实践 · 项目进度汇报", "s": 14, "b": True,
                            "c": RGBColor(0x9E, 0xC5, 0xFB)}])
        anim.add(kicker, FADE)

        title = self.box(slide, M, 2.06, 11.4, 1.0,
                         [{"t": "学生成绩管理系统", "s": 44, "b": True, "c": WHITE}])
        anim.add(title, WIPE)
        sub = self.box(slide, M, 3.18, 10.6, 0.5,
                       [{"t": "R1 项目骨架与数据库　·　R2 用户认证　—　已完成进度总结",
                         "s": 17, "b": True, "c": RGBColor(0xBF, 0xD7, 0xFF)}])
        anim.add(sub, FADE)
        tech = self.box(slide, M, 3.74, 10.6, 0.4,
                        [{"t": "Python 3.12 · Flask 3.1 · SQLAlchemy 2.0 · SQLite · Alembic · pytest",
                          "s": 12.5, "c": RGBColor(0x8A, 0xA6, 0xD6), "mono": True}])
        anim.add(tech, FADE)

        for i, (k, v) in enumerate([("当前进度", "2 / 12 轮"), ("自动化测试", "47 条全绿"),
                                    ("测试覆盖率", "98%"), ("已完成", "R1 · R2")]):
            x = M + i * 2.95
            c = self.rect(slide, x, 4.42, 2.62, 1.06, fill=RGBColor(0x1C, 0x38, 0x6C),
                          border=RGBColor(0x2E, 0x51, 0x92), radius=0.12)
            lines(c, [{"t": v, "s": 19, "b": True, "c": WHITE, "al": PP_ALIGN.CENTER, "sa": 2},
                      {"t": k, "s": 10.5, "c": RGBColor(0x9E, 0xC5, 0xFB),
                       "al": PP_ALIGN.CENTER}])
            c.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
            anim.add(c, FLOAT)

        foot = self.box(slide, M, 6.42, 11.8, 0.34,
                        [{"t": "汇报日期：2026-09-23　|　下一轮：R3 角色权限控制（RBAC）",
                          "s": 11.5, "c": RGBColor(0x7E, 0x9C, 0xD0)}])
        anim.add(foot, FADE)

        anim.flush()

    def slide_agenda(self) -> None:
        slide, anim = self.new("本次汇报", "汇报内容",
                               "从计划、设计、实现到验证，按四步说明项目当前状态")
        items = [
            ("01", "项目与进度", "目标、技术栈、12 轮路线图与 R1 / R2 完成情况", BLUE, BLUE_L),
            ("02", "设计思路", "应用工厂架构、6 张表的 ER 设计、冻结的权限矩阵", GREEN, GREEN_L),
            ("03", "R2 实现与演示", "认证流程、安全设计、真实界面演示与数据层验证", PURPLE, PURPLE_L),
            ("04", "验证与下一步", "测试与覆盖率、问题复盘、进度对照与后续计划", AMBER, AMBER_L),
        ]
        w, h, gap = (CW - 0.36) / 2, 2.2, 0.36
        for i, (num, title, desc, color, light) in enumerate(items):
            x = M + (i % 2) * (w + gap)
            y = CONTENT_TOP + (i // 2) * (h + 0.32)
            c = self.card(slide, x, y, w, h)
            n = self.rect(slide, x + 0.34, y + 0.34, 0.88, 0.88, fill=light, radius=0.16)
            lines(n, [{"t": num, "s": 22, "b": True, "c": color, "al": PP_ALIGN.CENTER}])
            n.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
            t = self.box(slide, x + 1.42, y + 0.36, w - 1.8, 0.45,
                         [{"t": title, "s": 17, "b": True, "c": INK}])
            d = self.box(slide, x + 1.42, y + 0.86, w - 1.8, h - 1.1,
                         [{"t": desc, "s": 12.5, "c": BODY}])
            Deck.group(anim,
                (c, FADE),
                (n, WIPE),
                (t, WIPE),
                (d, FADE),
            )
        anim.flush()

    def slide_overview(self) -> None:
        slide, anim = self.new("项目概览", "做一个什么系统",
                               "面向高校教学场景的学生成绩管理系统 · Web 应用（B/S 架构）")
        c = self.card(slide, M, CONTENT_TOP, 7.85, 2.05)
        lines(c, [
            {"t": "管理员 / 教师 / 学生", "s": 20, "b": True, "c": INK, "sa": 4},
            {"t": "一套系统三种角色：管理员维护基础数据，教师为自己所授课程录入成绩，"
                  "学生查询本人成绩单。", "s": 13, "c": BODY, "sa": 8},
            {"t": "不开放自主注册 —— 成绩系统不能让任何人自行注册，账号一律由管理员创建。",
             "s": 12.5, "b": True, "c": PINK},
        ])
        c.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        c.text_frame.margin_left = c.text_frame.margin_right = Inches(0.32)
        anim.add(c, FADE)

        feats = [("基础数据管理", "学生 / 教师 / 课程 增删改查"),
                 ("选课与成绩", "选课退课 · 成绩录入 · 成绩查询"),
                 ("统计与报表", "均分、及格率、分数段分布"),
                 ("批量数据", "Excel 导入导出 + 校验报告")]
        for i, (t, d) in enumerate(feats):
            y = CONTENT_TOP + 0.06 + i * 0.6
            b = self.rect(slide, M + 8.15, y, 4.08, 0.54, fill=WHITE, border=CARD_B, radius=0.14)
            dot = self.rect(slide, M + 8.35, y + 0.17, 0.2, 0.2, fill=SKY, shape=MSO_SHAPE.OVAL)
            tx = self.box(slide, M + 8.68, y + 0.03, 3.4, 0.26,
                          [{"t": t, "s": 12.5, "b": True, "c": INK}])
            dx = self.box(slide, M + 8.68, y + 0.27, 3.4, 0.24,
                          [{"t": d, "s": 10, "c": MUTED}])
            Deck.group(anim,
                (b, FADE),
                (dot, FADE),
                (tx, FADE),
                (dx, FADE),
            )

        strip = self.rect(slide, M, CONTENT_TOP + 2.72, CW, 1.9,
                          fill=RGBColor(0xF2, 0xF6, 0xFD),
                          border=RGBColor(0xD3, 0xE0, 0xF7), radius=0.05)
        anim.add(strip, FADE)
        tt = self.box(slide, M + 0.42, CONTENT_TOP + 2.86, 11.4, 0.34,
                      [{"t": "12 轮迭代，每轮一个功能，每轮结束都能运行、能演示、测试全绿",
                        "s": 15, "b": True, "c": NAVY}])
        anim.add(tt, WIPE)
        phases = [("阶段一 地基", "R1 骨架与数据库 · R2 用户认证 · R3 角色权限", BLUE, "已完成 2 / 3"),
                  ("阶段二 核心业务", "R4 学生 · R5 教师课程 · R6 选课 · R7 录入 · R8 查询", GREEN, "未开始"),
                  ("阶段三+四 增值与收尾", "R9 报表 · R10 Excel · R11 测试 · R12 部署交付", AMBER, "未开始")]
        pw = (CW - 1.0) / 3
        for i, (t, d, color, tag) in enumerate(phases):
            x = M + 0.5 + i * pw
            bar = self.rect(slide, x, CONTENT_TOP + 3.32, pw - 0.34, 0.055,
                            fill=color, shape=MSO_SHAPE.RECTANGLE)
            tx = self.box(slide, x, CONTENT_TOP + 3.44, pw - 0.3, 0.3,
                          [{"t": t, "s": 13, "b": True, "c": color}])
            dx = self.box(slide, x, CONTENT_TOP + 3.74, pw - 0.3, 0.62,
                          [{"t": d, "s": 11, "c": BODY, "sa": 4},
                           {"t": tag, "s": 10.5, "b": True, "c": MUTED}])
            Deck.group(anim,
                (bar, WIPE),
                (tx, WIPE),
                (dx, FADE),
            )
        anim.flush()

    def slide_tech(self) -> None:
        slide, anim = self.new("技术栈", "选型与版本约束",
                               "课程未指定语言，选 Python 生态；依赖已 pip freeze 冻结到 requirements.txt")
        items = [
            ("Python", "3.12.6", "运行时", BLUE, BLUE_L),
            ("Flask", "3.1.3", "Web 框架 · 应用工厂", GREEN, GREEN_L),
            ("SQLAlchemy", "2.0.54", "ORM · 2.0 类型化写法", PURPLE, PURPLE_L),
            ("Alembic", "1.20.0", "数据库迁移（不手工改表）", AMBER, AMBER_L),
            ("Flask-WTF", "1.3.0", "表单 + CSRF 防护", PINK, PINK_L),
            ("Werkzeug", "3.1.8", "口令哈希 scrypt", BLUE, BLUE_L),
            ("SQLite", "标准库", "开发 / 演示数据库", GREEN, GREEN_L),
            ("pytest", "8.4.2", "测试与覆盖率", PURPLE, PURPLE_L),
            ("openpyxl", "3.1.5", "Excel 导入导出（R10）", AMBER, AMBER_L),
            ("waitress", "3.0.2", "生产 WSGI 服务器（R12）", PINK, PINK_L),
        ]
        w, h, gx, gy = (CW - 4 * 0.22) / 5, 1.72, 0.22, 0.28
        for i, (name, ver, use, color, light) in enumerate(items):
            x = M + (i % 5) * (w + gx)
            y = CONTENT_TOP + 0.1 + (i // 5) * (h + gy)
            c = self.card(slide, x, y, w, h, fill=WHITE)
            top = self.rect(slide, x, y, w, 0.075, fill=color, shape=MSO_SHAPE.RECTANGLE)
            nm = self.box(slide, x, y + 0.22, w, 0.34,
                          [{"t": name, "s": 14.5, "b": True, "c": INK, "al": PP_ALIGN.CENTER}])
            vr = self.box(slide, x, y + 0.6, w, 0.4,
                          [{"t": ver, "s": 15, "b": True, "c": color, "al": PP_ALIGN.CENTER,
                            "mono": True}])
            us = self.box(slide, x, y + 1.06, w, 0.55,
                          [{"t": use, "s": 10, "c": MUTED, "al": PP_ALIGN.CENTER}])
            Deck.group(anim,
                (c, FLOAT),
                (top, WIPE),
                (nm, WIPE),
                (vr, FADE),
                (us, FADE),
            )

        note = self.rect(slide, M, CONTENT_TOP + 4.0, CW, 0.66, fill=BLUE_L,
                         border=RGBColor(0xC9, 0xDC, 0xFA), radius=0.1)
        nt = self.box(slide, M + 0.3, CONTENT_TOP + 4.08, CW - 0.6, 0.5,
                      [{"t": "架构参考 Flask 官方教程 Flaskr 的应用工厂与测试夹具写法；"
                            "业务代码全部自写，不直接复制参考实现。",
                        "s": 12, "b": True, "c": NAVY}])
        nt.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        anim.add(note, FADE)
        anim.add(nt, FADE)
        anim.flush()

    def slide_architecture(self) -> None:
        slide, anim = self.new("设计思路", "应用工厂 + 蓝图架构",
                               "create_app() 组装应用；按职责切分蓝图，每个蓝图一个 url_prefix")
        layers = [
            ("浏览器（B/S 前端）", "Jinja2 模板 + 静态样式 · 表单由服务端渲染", RGBColor(0xEE, 0xF4, 0xFD),
             RGBColor(0xC7, 0xDC, 0xFA), INK),
            ("Flask 应用 create_app()", "读取配置 → 初始化扩展 → 注册蓝图 → 注册 CLI 命令（init-db / seed）",
             BLUE_L, RGBColor(0xC2, 0xD8, 0xFB), NAVY),
            ("蓝图与视图层", "index 首页　|　auth 认证（R2）　|　admin / score / report（R4 起逐轮加入）",
             GREEN_L, GREEN_B, RGBColor(0x0B, 0x4F, 0x4A)),
            ("装饰器层 decorators.py", "@login_required（R2 已交付）　@role_required（R3）　+ 视图内行级校验",
             AMBER_L, RGBColor(0xF0, 0xC9, 0x8A), RGBColor(0x8A, 0x40, 0x04)),
            ("模型与数据层", "extensions.py 扩展单例（db / migrate / csrf）· models.py 6 张表 ORM",
             PURPLE_L, RGBColor(0xDD, 0xD0, 0xFA), RGBColor(0x50, 0x1F, 0xA8)),
            ("SQLite 数据库", "instance/gradeapp.sqlite · 结构变更一律走 Alembic 迁移",
             RGBColor(0xEC, 0xEF, 0xF3), RGBColor(0xCF, 0xD6, 0xE0), RGBColor(0x3A, 0x45, 0x54)),
        ]
        y = CONTENT_TOP
        ht, gap = 0.6, 0.16
        for i, (t, d, fill, border, color) in enumerate(layers):
            c = self.rect(slide, M, y, CW, ht, fill=fill, border=border, radius=0.14)
            tx = self.box(slide, M + 0.28, y + 0.03, 4.2, 0.54,
                          [{"t": t, "s": 13.5, "b": True, "c": color}])
            tx.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
            dx = self.box(slide, M + 4.7, y + 0.03, CW - 5.0, 0.54,
                          [{"t": d, "s": 11, "c": BODY}])
            dx.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
            Deck.group(anim,
                (c, FADE),
                (tx, WIPE),
                (dx, FADE),
            )
            if i < len(layers) - 1:
                ar = self.arrow(slide, SW / 2 - 0.09, y + ht + 0.02, 0.18, gap - 0.04)
                anim.add(ar, FADE)
            y += ht + gap
        anim.flush()

    def slide_er(self) -> None:
        slide, anim = self.new("设计思路", "数据模型：6 张表（已冻结）",
                               "ER 关系：user ─ student ─ enrollment ─ course ─ teacher ─ user，"
                               "score 挂在 enrollment 上")
        tables = [
            ("user", "id · username★ · password_hash · role · real_name · is_active", M + 0.1,
             CONTENT_TOP - 0.02, 3.0, 1.02, BLUE, BLUE_L),
            ("student", "id · user_id → user.id（唯一）· sno★ · name · gender · class_name", M + 3.75,
             CONTENT_TOP + 1.38, 3.5, 1.02, GREEN, GREEN_L),
            ("enrollment", "id · student_id → student.id · course_id → course.id", M + 3.75,
             CONTENT_TOP + 3.05, 3.5, 1.02, PURPLE, PURPLE_L),
            ("course", "id · code★ · name · credit · hours · teacher_id · semester · capacity",
             M + 7.7, CONTENT_TOP + 1.38, 4.0, 1.02, AMBER, AMBER_L),
            ("teacher", "id · user_id → user.id（唯一）· tno★ · name · title · department", M + 7.7,
             CONTENT_TOP + 3.05, 4.0, 1.02, PINK, PINK_L),
            ("score", "id · enrollment_id → enrollment.id · exam_type · score 0~100 · updated_by",
             M + 0.1, CONTENT_TOP + 3.05, 3.25, 1.02, RGBColor(0x0E, 0x74, 0x90),
             RGBColor(0xDF, 0xF1, 0xF7)),
        ]
        shapes = {}
        for name, fields, x, y, w, h, color, light in tables:
            c = self.rect(slide, x, y, w, h, fill=WHITE, border=color, radius=0.1)
            head = self.rect(slide, x, y, w, 0.32, fill=light, radius=0.26)
            hd = self.box(slide, x + 0.16, y + 0.01, w - 0.3, 0.3,
                          [{"t": name, "s": 13, "b": True, "c": color, "mono": True}])
            hd.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
            fd = self.box(slide, x + 0.16, y + 0.34, w - 0.3, 0.64,
                          [{"t": fields, "s": 9.5, "c": BODY}])
            shapes[name] = (x, y, w, h)
            Deck.group(anim,
                (c, FLOAT),
                (head, FADE),
                (hd, WIPE),
                (fd, FADE),
            )

        def rel(a, b, label):
            ax, ay, aw, ah = shapes[a]
            bx, by, bw, bh = shapes[b]
            if ay < by:  # a 在上
                self.connector(slide, MSO_CONNECTOR.STRAIGHT, ax + aw / 2, ay + ah,
                               bx + bw / 2, by, label)
            else:  # a 在下
                self.connector(slide, MSO_CONNECTOR.STRAIGHT, ax + aw / 2, ay,
                               bx + bw / 2, by + bh, label)

        rel("student", "user", "1:1")
        rel("enrollment", "student", "N:1")
        rel("score", "enrollment", "N:1")
        self.connector(slide, MSO_CONNECTOR.STRAIGHT, M + 3.3, CONTENT_TOP + 0.5,
                       M + 7.7, CONTENT_TOP + 0.5, "1:1（教师也是账号）", dash=True)
        self.connector(slide, MSO_CONNECTOR.STRAIGHT, M + 5.5, CONTENT_TOP + 2.4,
                       M + 9.7, CONTENT_TOP + 2.4, "N:1（课程由教师讲授）")

        leg = self.box(slide, M + 0.1, CONTENT_TOP + 4.16, 11.5, 0.34,
                       [{"t": "★ = 唯一约束　|　外键方向：user ← student / teacher，student + course → enrollment，"
                             "enrollment → score", "s": 10.5, "c": MUTED}])
        anim.add(leg, FADE)
        anim.flush()

    def slide_design_points(self) -> None:
        slide, anim = self.new("设计思路", "三个有意为之的设计决定",
                               "这些是验收时最容易被追问的地方，先讲清楚理由")
        blocks = [
            ("enrollment 不是冗余表", BLUE, BLUE_L,
             ["教师录入成绩时必须先知道“这门课有哪些学生”，这份名单只能来自选课表；",
              "因此 enrollment 是成绩录入的前置数据，不是可有可无的中间表。"]),
            ("score 挂在 enrollment 上", GREEN, GREEN_L,
             ["而不是直接挂 (student_id, course_id) —— 从数据库层面杜绝“给未选课的学生打分”；",
              "enrollment 删除时成绩级联删除，数据不会留下孤儿记录。"]),
            ("exam_type 多次考核 + 唯一约束", PURPLE, PURPLE_L,
             ["同一门课支持平时 / 期中 / 期末多次考核，UNIQUE(enrollment_id, exam_type) 防重复录入；",
              "有意不加数据库 CHECK，便于 R10 Excel 导入时扩展考核类型。"]),
        ]
        w = (CW - 0.44) / 3
        for i, (title, color, light, body) in enumerate(blocks):
            x = M + i * (w + 0.22)
            c = self.card(slide, x, CONTENT_TOP + 0.15, w, 3.4, fill=WHITE)
            top = self.rect(slide, x, CONTENT_TOP + 0.15, w, 0.075, fill=color,
                            shape=MSO_SHAPE.RECTANGLE)
            num = self.rect(slide, x + 0.28, CONTENT_TOP + 0.42, 0.62, 0.62, fill=light,
                            radius=0.2)
            lines(num, [{"t": f"0{i + 1}", "s": 16, "b": True, "c": color,
                         "al": PP_ALIGN.CENTER}])
            num.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
            t = self.box(slide, x + 0.28, CONTENT_TOP + 1.16, w - 0.56, 0.72,
                         [{"t": title, "s": 15, "b": True, "c": INK}])
            b = self.box(slide, x + 0.28, CONTENT_TOP + 1.92, w - 0.56, 1.5,
                         [{"t": body[0], "s": 11.5, "c": BODY, "sa": 8},
                          {"t": body[1], "s": 11.5, "c": BODY}])
            for shp, pre in ((c, FLOAT), (top, WIPE), (num, WIPE), (t, WIPE), (b, FADE)):
                anim.add(shp, pre)

        strip = self.rect(slide, M, CONTENT_TOP + 3.78, CW, 0.78, fill=RGBColor(0xF2, 0xF6, 0xFD),
                          border=RGBColor(0xD3, 0xE0, 0xF7), radius=0.1)
        st = self.box(slide, M + 0.32, CONTENT_TOP + 3.88, CW - 0.64, 0.6,
                      [{"t": "权限矩阵（已冻结，R3 起逐条落地）：admin 全量 · teacher 仅自己授课的课程 · "
                            "student 仅本人；@role_required 只挡角色，“是不是自己教的课”必须在视图内做行级校验。",
                        "s": 11.5, "b": True, "c": NAVY}])
        st.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        anim.add(strip, FADE)
        anim.add(st, FADE)
        anim.flush()

    def slide_r1(self) -> None:
        slide, anim = self.new("R1 回顾", "R1 — 项目骨架与数据库",
                               "2026-09-22 完成 · 交付物：能跑的 Flask 应用 + 6 张表 + 首次 git 提交")
        left = self.card(slide, M, CONTENT_TOP, 6.55, 4.5)
        lt = self.box(slide, M + 0.34, CONTENT_TOP + 0.22, 6.0, 0.4,
                      [{"t": "这一轮做了什么", "s": 15, "b": True, "c": INK}])
        items = [
            ("应用工厂", "gradeapp/__init__.py：create_app() + init-db / seed 命令"),
            ("扩展单例", "extensions.py：db / migrate / csrf"),
            ("数据模型", "models.py：user、student、teacher、course、enrollment、score"),
            ("迁移脚本", "migrations/versions/fba8e95c58f8_initial_schema…py（Alembic）"),
            ("依赖冻结", "requirements.txt（pip freeze）· pyproject.toml · .flaskenv"),
            ("测试夹具", "tests/conftest.py：tempfile 临时库隔离，12 条测试"),
        ]
        y = CONTENT_TOP + 0.72
        for t, d in items:
            dot = self.rect(slide, M + 0.36, y + 0.09, 0.18, 0.18, fill=BLUE,
                            shape=MSO_SHAPE.OVAL)
            tx = self.box(slide, M + 0.68, y - 0.02, 1.72, 0.3,
                          [{"t": t, "s": 12.5, "b": True, "c": INK}])
            dx = self.box(slide, M + 2.46, y - 0.02, 3.9, 0.3,
                          [{"t": d, "s": 10.5, "c": BODY}])
            Deck.group(anim,
                (dot, FADE),
                (tx, FADE),
                (dx, FADE),
            )
            y += 0.56

        right = self.card(slide, M + 6.8, CONTENT_TOP, 5.43, 4.5, fill=WHITE)
        rt = self.box(slide, M + 7.14, CONTENT_TOP + 0.22, 4.8, 0.4,
                      [{"t": "验证到的事实", "s": 15, "b": True, "c": INK}])
        anim.add(rt, FADE)
        metrics = [("12 条", "测试全部通过"), ("97%", "覆盖率"), ("7 张表", "6 业务表 + alembic_version"),
                   ("3 + 1 + 1 + 1", "user / student / teacher / course 种子数据"), ("0", "明文口令（全部 scrypt 哈希）")]
        y = CONTENT_TOP + 0.78
        for v, k in metrics:
            vb = self.box(slide, M + 7.14, y, 1.85, 0.36,
                          [{"t": v, "s": 15, "b": True, "c": BLUE}])
            kb = self.box(slide, M + 9.02, y + 0.03, 3.05, 0.36,
                          [{"t": k, "s": 10.5, "c": BODY}])
            anim.add(vb, WIPE)
            anim.add(kb, FADE)
            y += 0.6
        tag = self.rect(slide, M + 7.14, CONTENT_TOP + 3.9, 1.6, 0.42, fill=GREEN_L, radius=0.5)
        lines(tag, [{"t": "R1 ✅ 已完成", "s": 11, "b": True, "c": GREEN, "al": PP_ALIGN.CENTER}])
        tag.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        Deck.group(anim,
            (tag, FADE),
            (left, FADE),
            (lt, WIPE),
            (right, FADE),
        )
        anim.flush()

    # ---------- R2 主体 ----------
    def slide_r2_flow(self) -> None:
        slide, anim = self.new("R2 实现", "认证流程：登录 / 登出 / 会话保持",
                               "2026-09-23 完成 · 交付：auth.py、decorators.py、base.html、login.html、35 条测试")
        steps = [
            ("1", "提交表单", "/auth/login POST\n用户名 + 口令 + CSRF token", BLUE, BLUE_L),
            ("2", "查库比对", "select(User)\ncheck_password() scrypt", GREEN, GREEN_L),
            ("3", "签发会话", "session[user_id]\n+ _token 指纹", PURPLE, PURPLE_L),
            ("4", "保持登录", "permanent 7 天\nHttpOnly SameSite=Lax", AMBER, AMBER_L),
            ("5", "登出", "POST /auth/logout\n清空会话", PINK, PINK_L),
        ]
        w = (CW - 4 * 0.3) / 5
        for i, (num, t, d, color, light) in enumerate(steps):
            x = M + i * (w + 0.3)
            c = self.card(slide, x, CONTENT_TOP + 0.06, w, 2.0, fill=WHITE)
            n = self.rect(slide, x + 0.24, CONTENT_TOP + 0.26, 0.54, 0.54, fill=light, radius=0.5)
            lines(n, [{"t": num, "s": 15, "b": True, "c": color, "al": PP_ALIGN.CENTER}])
            n.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
            tx = self.box(slide, x + 0.24, CONTENT_TOP + 0.92, w - 0.48, 0.3,
                          [{"t": t, "s": 13.5, "b": True, "c": INK}])
            dx = self.box(slide, x + 0.24, CONTENT_TOP + 1.26, w - 0.48, 0.72,
                          [{"t": d, "s": 10.5, "c": BODY, "mono": True}])
            Deck.group(anim,
                (c, FLOAT),
                (n, WIPE),
                (tx, WIPE),
                (dx, FADE),
            )
            if i < 4:
                ar = self.rect(slide, x + w + 0.05, CONTENT_TOP + 0.96, 0.2, 0.2,
                               fill=SKY, shape=MSO_SHAPE.RIGHT_ARROW)
                anim.add(ar, FADE)

        box = self.rect(slide, M, CONTENT_TOP + 2.3, CW, 2.3, fill=RGBColor(0xF2, 0xF6, 0xFD),
                        border=RGBColor(0xD3, 0xE0, 0xF7), radius=0.05)
        anim.add(box, FADE)
        bt = self.box(slide, M + 0.42, CONTENT_TOP + 2.46, 6.2, 0.34,
                      [{"t": "会话指纹：一句话讲清楚", "s": 14.5, "b": True, "c": NAVY}])
        anim.add(bt, WIPE)
        code = self.rect(slide, M + 0.42, CONTENT_TOP + 2.88, 6.2, 0.86, fill=WHITE,
                         border=RGBColor(0xC9, 0xDC, 0xFA), radius=0.08)
        lines(code, [
            {"t": "# 载荷 = [user_id, sha256(password_hash)[:16]]，用 SECRET_KEY 签名",
             "s": 10, "c": MUTED, "mono": True, "sa": 3},
            {"t": 'session["_token"] = serializer.dumps([user.id, fingerprint])',
             "s": 10.5, "b": True, "c": NAVY, "mono": True},
        ])
        code.text_frame.margin_left = Inches(0.16)
        code.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        anim.add(code, FADE)
        tail = self.box(slide, M + 0.42, CONTENT_TOP + 3.86, 6.2, 0.62,
                        [{"t": "校验时比对「签名有效 + 未过期 + 口令哈希摘要一致」，任何一条不成立即清空会话。",
                          "s": 11, "c": BODY}])
        anim.add(tail, FADE)
        expl = self.box(slide, M + 6.9, CONTENT_TOP + 2.46, 5.3, 2.0,
                        [{"t": "为什么这么做", "s": 14.5, "b": True, "c": NAVY, "sa": 6},
                         {"t": "· 管理员改了某人口令，或停用账号 → 旧 cookie 的下一次请求立即失效；",
                          "s": 11.5, "c": BODY, "sa": 4},
                         {"t": "· cookie 里只有口令哈希的短摘要，不出现完整哈希；",
                          "s": 11.5, "c": BODY, "sa": 4},
                         {"t": "· 这也是“改密码即全端下线”的实现方式。", "s": 11.5, "c": BODY}])
        anim.add(expl, FADE)
        anim.flush()

    def slide_r2_security(self) -> None:
        slide, anim = self.new("R2 实现", "安全设计：六个必须做对的细节",
                               "成绩系统涉及敏感数据，认证环节的边界比“能登录”更重要")
        items = [
            ("口令只存哈希", "werkzeug scrypt，形如 scrypt:32768:8:1$…；库中不存在明文口令。", BLUE),
            ("不泄露账号是否存在", "“用户不存在”与“口令错误”返回同一句提示，避免账号枚举。", GREEN),
            ("停用账号立即拦截", "is_active=False 无法登录；已在线会话也会被吊销。", PURPLE),
            ("会话指纹", "改口令 / 停用后旧会话立即失效，无需额外的黑名单。", AMBER),
            ("CSRF 防护", "全局 CSRFProtect；登录表单与导航登出表单都带 csrf_token。", PINK),
            ("开放重定向防护", "?next= 只接受站内相对地址，//evil.com 与 javascript: 一律回首页。", RGBColor(0x0E, 0x74, 0x90)),
        ]
        w = (CW - 2 * 0.34) / 3
        h = 2.1
        for i, (t, d, color) in enumerate(items):
            x = M + (i % 3) * (w + 0.34)
            y = CONTENT_TOP + 0.16 + (i // 3) * (h + 0.24)
            c = self.card(slide, x, y, w, h, fill=WHITE)
            top = self.rect(slide, x, y, 0.075, h, fill=color, shape=MSO_SHAPE.RECTANGLE)
            tx = self.box(slide, x + 0.32, y + 0.26, w - 0.6, 0.36,
                          [{"t": t, "s": 14.5, "b": True, "c": INK}])
            dx = self.box(slide, x + 0.32, y + 0.78, w - 0.6, 1.1,
                          [{"t": d, "s": 11.5, "c": BODY}])
            Deck.group(anim,
                (c, FLOAT),
                (top, WIPE),
                (tx, WIPE),
                (dx, FADE),
            )

        strip = self.rect(slide, M, CONTENT_TOP + 4.34, CW, 0.5, fill=AMBER_L,
                          border=RGBColor(0xF0, 0xC9, 0x8A), radius=0.1)
        st = self.box(slide, M + 0.3, CONTENT_TOP + 4.38, CW - 0.6, 0.42,
                      [{"t": "已知边界：目前只有 @login_required（登录才能访问）；"
                            "按角色的 @role_required 与 403 页面在 R3 补齐 —— 现在还没有真正的权限控制。",
                        "s": 11, "b": True, "c": AMBER}])
        st.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        anim.add(strip, FADE)
        anim.add(st, FADE)
        anim.flush()

    def slide_demo_login(self) -> None:
        slide, anim = self.new("成果演示", "演示一：登录界面与失败提示",
                               "截图取自真实运行的服务（flask run + Edge 无头浏览器）")
        x1, x2 = M, M + 6.42
        w = 5.81
        s1, pw, ph = self.picture_fit(slide, "login_full.png", x1, CONTENT_TOP + 0.06, w, 4.3)
        anim.add(s1, FLOAT)
        cb1 = self.box(slide, x1, CONTENT_TOP + 4.42, w, 0.32,
                       [{"t": "① 登录页：账号 + 口令，页面同时列出演示账号（仅教学用）",
                         "s": 11, "b": True, "c": INK, "al": PP_ALIGN.CENTER}])
        anim.add(cb1, FADE)

        s2, _, _ = self.picture_fit(slide, "login_error_full.png", x2, CONTENT_TOP + 0.06, w, 4.3)
        anim.add(s2, FLOAT)
        cb2 = self.box(slide, x2, CONTENT_TOP + 4.42, w, 0.32,
                       [{"t": "② 口令错误：停在登录页提示“用户名或口令错误”，且不发放会话",
                         "s": 11, "b": True, "c": INK, "al": PP_ALIGN.CENTER}])
        anim.add(cb2, FADE)
        anim.flush()

    def slide_demo_home(self) -> None:
        slide, anim = self.new("成果演示", "演示二：登录成功后的首页",
                               "导航栏显示姓名 + 角色徽标 + 退出登录；首页显示会话状态与 6 张表的实时记录数")
        s, pw, ph = self.picture_fit(slide, "home_admin_plain.png", M, CONTENT_TOP + 0.06,
                                     8.05, 4.3)
        anim.add(s, FLOAT)
        x = M + 8.35
        w = 3.88
        pts = [
            ("admin 管理员", "导航：首页 · 学生管理 · 账号管理（灰显占位，R4/R5 启用）", BLUE),
            ("会话已保持", "刷新页面甚至重开浏览器仍是登录态，cookie 有效期 7 天", GREEN),
            ("数据层可验证", "首页表格实时查库：user 3 · student 1 · teacher 1 · course 1", PURPLE),
            ("已安全退出", "退出登录只接受 POST（GET 返回 405），清空会话后回登录页", AMBER),
        ]
        y = CONTENT_TOP + 0.06
        for t, d, color in pts:
            c = self.card(slide, x, y, w, 1.0, fill=WHITE)
            bar = self.rect(slide, x, y + 0.14, 0.06, 0.72, fill=color, shape=MSO_SHAPE.RECTANGLE)
            tx = self.box(slide, x + 0.2, y + 0.1, w - 0.36, 0.3,
                          [{"t": t, "s": 12.5, "b": True, "c": INK}])
            dx = self.box(slide, x + 0.2, y + 0.4, w - 0.36, 0.54,
                          [{"t": d, "s": 10.5, "c": BODY}])
            Deck.group(anim,
                (c, FADE),
                (bar, WIPE),
                (tx, WIPE),
                (dx, FADE),
            )
            y += 1.12
        anim.flush()

    def slide_demo_roles(self) -> None:
        slide, anim = self.new("成果演示", "演示三：三种角色看到不同的导航与首页",
                               "同一套系统、同一份代码，按角色渲染菜单 —— 前端区分只是体验，服务端鉴权在 R3")
        names = [("role_admin.png", "admin 管理员", "学生管理 · 账号管理", BLUE),
                 ("role_teacher.png", "teacher 教师", "我的课程（R7）", GREEN),
                 ("role_student.png", "student 学生", "选课 · 我的成绩（R6 / R8）", PURPLE)]
        w = (CW - 0.44) / 3
        for i, (f, name, nav, color) in enumerate(names):
            x = M + i * (w + 0.22)
            c = self.card(slide, x, CONTENT_TOP + 0.05, w, 3.42, fill=WHITE)
            top = self.rect(slide, x, CONTENT_TOP + 0.05, w, 0.06, fill=color,
                            shape=MSO_SHAPE.RECTANGLE)
            s, pw, ph = self.picture_fit(slide, f, x + 0.12, CONTENT_TOP + 0.22, w - 0.24, 2.18)
            tx = self.box(slide, x + 0.24, CONTENT_TOP + 2.48, w - 0.48, 0.3,
                          [{"t": name, "s": 13.5, "b": True, "c": color}])
            dx = self.box(slide, x + 0.24, CONTENT_TOP + 2.8, w - 0.48, 0.56,
                          [{"t": f"导航：{nav}", "s": 10.5, "c": BODY}])
            Deck.group(anim,
                (c, FLOAT),
                (top, WIPE),
                (s, FLOAT),
                (tx, WIPE),
                (dx, FADE),
            )

        note = self.rect(slide, M, CONTENT_TOP + 3.5, CW, 0.58, fill=AMBER_L,
                         border=RGBColor(0xF0, 0xC9, 0x8A), radius=0.1)
        nt = self.box(slide, M + 0.3, CONTENT_TOP + 3.53, CW - 0.6, 0.36,
                      [{"t": "注意：菜单项的差异只是“按角色渲染”，当前还没有 @role_required —— "
                            "直接敲 URL 仍能访问受限路由，所以 R3 必须补上服务端鉴权与 403 页面。",
                        "s": 11.5, "b": True, "c": AMBER}])
        nt.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        anim.add(note, FADE)
        anim.add(nt, FADE)
        anim.flush()

    def slide_demo_data(self) -> None:
        slide, anim = self.new("成果演示", "演示四：数据层与迁移的证据",
                               "首页表格实时查库；建表由 Alembic 迁移完成，测试会校验“模型与迁移无漂移”")
        pts = [
            ("6 张业务表全部建成", "flask init-db 走 Alembic，db current 显示 fba8e95c58f8 (head)", GREEN),
            ("种子数据幂等", "flask seed 重复执行不产生重复数据：user 3 · student 1 · teacher 1 · course 1", BLUE),
            ("约束由数据库强制", "学号 / 工号 / 课程代码唯一；UNIQUE(student_id, course_id)；score 0~100", PURPLE),
            ("迁移漂移检测", "测试对比 ORM 元数据与迁移脚本，忘记生成迁移会直接失败", AMBER),
        ]
        y = CONTENT_TOP + 0.05
        for t, d, color in pts:
            c = self.card(slide, M, y, 6.0, 1.06, fill=WHITE)
            bar = self.rect(slide, M, y + 0.16, 0.06, 0.74, fill=color, shape=MSO_SHAPE.RECTANGLE)
            tx = self.box(slide, M + 0.24, y + 0.12, 5.5, 0.32,
                          [{"t": t, "s": 12.5, "b": True, "c": INK}])
            dx = self.box(slide, M + 0.24, y + 0.44, 5.5, 0.56,
                          [{"t": d, "s": 10.5, "c": BODY}])
            Deck.group(anim,
                (c, FADE),
                (bar, WIPE),
                (tx, WIPE),
                (dx, FADE),
            )
            y += 1.16

        s, pw, ph = self.picture_fit(slide, "tables.png", M + 6.4, CONTENT_TOP + 0.85, 5.8, 2.2)
        anim.add(s, FLOAT)
        cap = self.box(slide, M + 6.4, CONTENT_TOP + 3.2, 5.8, 0.32,
                       [{"t": "首页“数据表（共 6 张）”区块 —— 记录数每次请求实时查库",
                         "s": 10.5, "c": MUTED, "al": PP_ALIGN.CENTER}])
        anim.add(cap, FADE)
        anim.flush()

    def slide_test(self) -> None:
        slide, anim = self.new("质量验证", "测试：47 条全绿，覆盖率 98%",
                               "R1 的 12 条（骨架 / 模型 / 约束）+ R2 的 35 条（认证全路径）")
        rows = [
            ("R1", "骨架与模型", "12", "97%", "应用工厂、6 张表字段、迁移无漂移、唯一与 CHECK 约束", BLUE),
            ("R2", "用户认证", "35", "98%", "登录成功 / 失败路径 / 登出 / 会话保持与失效 / 重定向防护", GREEN),
        ]
        y = CONTENT_TOP + 0.1
        for tag, name, cnt, cov, desc, color in rows:
            c = self.card(slide, M, y, 6.5, 1.5, fill=WHITE)
            chip = self.chip(slide, M + 0.24, y + 0.2, 0.78, 0.42, tag, fill=color, color=WHITE)
            tx = self.box(slide, M + 1.18, y + 0.16, 5.1, 0.32,
                          [{"t": f"{name} · {cnt} 条 · 覆盖率 {cov}", "s": 14, "b": True, "c": INK}])
            dx = self.box(slide, M + 1.18, y + 0.54, 5.15, 0.78,
                          [{"t": desc, "s": 11, "c": BODY}])
            Deck.group(anim,
                (c, FLOAT),
                (chip, WIPE),
                (tx, WIPE),
                (dx, FADE),
            )
            y += 1.6

        r = self.card(slide, M + 6.75, CONTENT_TOP + 0.1, 5.48, 3.16, fill=WHITE)
        rt = self.box(slide, M + 7.05, CONTENT_TOP + 0.28, 5.0, 0.34,
                      [{"t": "重点覆盖的边界", "s": 14, "b": True, "c": INK}])
        anim.add(rt, WIPE)
        bullets = [
            "口令为空 / 用户不存在 / 口令错误 → 均不发放会话",
            "已登录再访问登录页 → 直接回首页",
            "登出 GET → 405；缺 CSRF token 的 POST → 400",
            "改口令 / 停用账号后旧会话立即失效",
            "伪造与过期的会话指纹被拒绝",
            "?next= 开放重定向（//evil.com、javascript:）被拦",
        ]
        by = CONTENT_TOP + 0.72
        for b in bullets:
            dot = self.rect(slide, M + 7.05, by + 0.08, 0.14, 0.14, fill=SKY, shape=MSO_SHAPE.OVAL)
            tx = self.box(slide, M + 7.3, by - 0.04, 4.7, 0.34, [{"t": b, "s": 11, "c": BODY}])
            anim.add(dot, FADE)
            anim.add(tx, FADE)
            by += 0.4
        anim.add(r, FADE)

        s, pw, ph = self.picture_fit(slide, "tables.png", M, CONTENT_TOP + 3.3, 5.2, 1.4)
        anim.add(s, FLOAT)
        cov = self.rect(slide, M + 5.5, CONTENT_TOP + 3.34, 6.73, 1.32,
                        fill=RGBColor(0xF2, 0xF6, 0xFD), border=RGBColor(0xD3, 0xE0, 0xF7),
                        radius=0.1)
        lines(cov, [
            {"t": "分模块覆盖率", "s": 12.5, "b": True, "c": NAVY, "sa": 4},
            {"t": "auth.py 100% · decorators.py 100% · models.py 100% · extensions.py 100% · __init__.py 95%",
             "s": 11, "c": BODY, "sa": 4},
            {"t": "注意：R11 要求的是“权限矩阵 + 边界”覆盖，当前覆盖率不能替代它。",
             "s": 10.5, "b": True, "c": AMBER},
        ])
        cov.text_frame.margin_left = Inches(0.26)
        cov.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        anim.add(cov, FADE)
        anim.flush()

    def slide_issues(self) -> None:
        slide, anim = self.new("复盘", "R2 遇到的三个问题与解决方式",
                               "这一节的模板就是 docs/验收记录.md 中的“遇到的问题 / 如何解决”")
        items = [
            ("模板重构后首页测试被影响",
             "index.html 改为继承 base.html，原有 12 条断言必须继续成立。",
             "只“追加”登录状态区块、不改既有内容；重构后立刻重跑 test_app.py，全绿。", BLUE, BLUE_L),
            ("导航里的登出表单怎么带 CSRF token",
             "登出按钮在 base.html 的导航里，每个页面（含未登录页面）都要能渲染它。",
             "用 app_context_processor 注入空的 LogoutForm()，模板里 hidden_tag() 输出 token —— "
             "表单仍由 Flask-WTF 生成，不绕过 CSRF。", GREEN, GREEN_L),
            ("受限环境下临时目录不可用",
             "为验证“CSRF 真会拦截”写了新测试，pytest 的 tmp_path 在受限环境下创建目录失败。",
             "改用与 conftest.py 一致的 tempfile.mkstemp()，finally 里按 "
             "session.remove → drop_all → engine.dispose → 删文件 的顺序释放。", AMBER, AMBER_L),
        ]
        y = CONTENT_TOP + 0.05
        for t, prob, fix, color, light in items:
            c = self.card(slide, M, y, CW, 1.38, fill=WHITE)
            bar = self.rect(slide, M, y + 0.18, 0.06, 1.02, fill=color, shape=MSO_SHAPE.RECTANGLE)
            tx = self.box(slide, M + 0.26, y + 0.12, CW - 0.6, 0.32,
                          [{"t": t, "s": 13.5, "b": True, "c": INK}])
            pb = self.chip(slide, M + 0.26, y + 0.52, 0.62, 0.3, "问题", fill=light, color=color,
                           size=10)
            px = self.box(slide, M + 1.02, y + 0.48, 5.0, 0.72,
                          [{"t": prob, "s": 11, "c": BODY}])
            fx = self.box(slide, M + 6.2, y + 0.48, CW - 6.46, 0.72,
                          [{"t": fix, "s": 11, "c": BODY}])
            for shp, pre in ((c, FLOAT), (bar, WIPE), (tx, WIPE), (pb, FADE), (px, FADE), (fx, FADE)):
                anim.add(shp, pre)
            y += 1.48
        anim.flush()

    def slide_roadmap(self) -> None:
        slide, anim = self.new("进度对照", "12 轮路线图与当前坐标",
                               "已完成 2 / 12 轮；每轮结束系统都处于“可运行、可演示、测试全绿”状态")
        groups = [
            ("阶段一 · 地基", "R1 – R3", BLUE, BLUE_L,
             [("R1", "项目骨架与数据库", "done"), ("R2", "用户认证", "done"),
              ("R3", "角色权限 RBAC", "next")]),
            ("阶段二 · 核心业务", "R4 – R8", GREEN, GREEN_L,
             [("R4", "学生信息管理", ""), ("R5", "教师与课程管理", ""), ("R6", "选课管理", ""),
              ("R7", "成绩录入", ""), ("R8", "成绩查询", "")]),
            ("阶段三 · 增值功能", "R9 – R10", AMBER, AMBER_L,
             [("R9", "统计报表", ""), ("R10", "Excel 导入导出", "")]),
            ("阶段四 · 收尾", "R11 – R12", PURPLE, PURPLE_L,
             [("R11", "测试体系完善", ""), ("R12", "部署与交付", "")]),
        ]
        w = (CW - 3 * 0.26) / 4
        for i, (name, span, color, light, rounds) in enumerate(groups):
            x = M + i * (w + 0.26)
            c = self.card(slide, x, CONTENT_TOP + 0.1, w, 3.5, fill=WHITE)
            head = self.rect(slide, x, CONTENT_TOP + 0.1, w, 0.66, fill=light, radius=0.16)
            ht = self.box(slide, x + 0.2, CONTENT_TOP + 0.16, w - 0.4, 0.28,
                          [{"t": name, "s": 12.5, "b": True, "c": color}])
            hs = self.box(slide, x + 0.2, CONTENT_TOP + 0.42, w - 0.4, 0.26,
                          [{"t": f"{span} · {len(rounds)} 轮", "s": 10, "c": MUTED}])
            Deck.group(anim,
                (c, FLOAT),
                (head, FADE),
                (ht, WIPE),
                (hs, FADE),
            )
            y = CONTENT_TOP + 0.9
            for code, label, state in rounds:
                fill = light if state == "done" else (RGBColor(0xFF, 0xF4, 0xE0) if state == "next" else RGBColor(0xF4, 0xF6, 0xF9))
                bd = color if state == "done" else (RGBColor(0xE8, 0xA9, 0x5B) if state == "next" else CARD_B)
                b = self.rect(slide, x + 0.18, y, w - 0.36, 0.5, fill=fill, border=bd, radius=0.16)
                code_c = color if state else MUTED
                lines(b, [{"t": f"{code}  {label}" + ("  ✅" if state == "done" else ("  ← 下一轮" if state == "next" else "")),
                           "s": 10.5, "b": state != "", "c": code_c}])
                b.text_frame.margin_left = Inches(0.12)
                b.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
                anim.add(b, WIPE)
                y += 0.58
        anim.flush()

    def slide_next(self) -> None:
        slide, anim = self.new("下一步", "收尾：当前状态与接下来的计划",
                               "系统现在是可运行、可演示、测试全绿的状态，可以从这一轮直接继续")
        left = self.card(slide, M, CONTENT_TOP, 5.9, 4.5, fill=WHITE)
        lt = self.box(slide, M + 0.32, CONTENT_TOP + 0.22, 5.3, 0.36,
                      [{"t": "当前状态", "s": 15, "b": True, "c": INK}])
        anim.add(lt, WIPE)
        rows = [("已完成", "R1 骨架与数据库 · R2 用户认证（2 / 12）"),
                ("可演示", "三角色登录 / 登出 / 会话保持 / 安全边界"),
                ("可运行", "flask init-db → flask seed → flask run 三步起服务"),
                ("质量", "47 条测试全绿，覆盖率 98%，无遗留缺陷"),
                ("文档", "README、验收记录、进度计划（唯一入口文档）同步更新")]
        y = CONTENT_TOP + 0.7
        for k, v in rows:
            kb = self.chip(slide, M + 0.32, y + 0.02, 0.96, 0.34, k, fill=BLUE_L, color=BLUE, size=10.5)
            vb = self.box(slide, M + 1.42, y - 0.04, 4.2, 0.6,
                          [{"t": v, "s": 11.5, "c": BODY}])
            anim.add(kb, FADE)
            anim.add(vb, FADE)
            y += 0.68
        foot = self.box(slide, M + 0.32, CONTENT_TOP + 4.04, 5.3, 0.3,
                        [{"t": "阻塞 / 待确认：无", "s": 11.5, "b": True, "c": GREEN}])
        anim.add(foot, FADE)

        right = self.card(slide, M + 6.15, CONTENT_TOP, 6.08, 4.5,
                          fill=RGBColor(0xF2, 0xF6, 0xFD), border=RGBColor(0xD3, 0xE0, 0xF7))
        rt = self.box(slide, M + 6.45, CONTENT_TOP + 0.22, 5.5, 0.36,
                      [{"t": "接下来的两步", "s": 15, "b": True, "c": NAVY}])
        anim.add(rt, WIPE)
        steps = [
            ("R3", "角色权限控制（RBAC）",
             "decorators.py 补 @role_required(*roles)、新增 403 页面、导航与首页按角色区分、"
             "tests/test_permissions.py 逐条覆盖权限矩阵；重点：行级校验，前端隐藏菜单不算权限控制。"),
            ("R4 → R5", "学生 / 教师 / 课程管理",
             "开始出现网页 CRUD 界面：分页、搜索、Flask-WTF 表单校验；"
             "数据库结构不变，继续走 Alembic。"),
        ]
        y = CONTENT_TOP + 0.74
        for code, title, desc in steps:
            c = self.rect(slide, M + 6.45, y, 5.48, 1.78, fill=WHITE, border=CARD_B, radius=0.08)
            box = self.rect(slide, M + 6.72, y + 0.26, 0.86, 0.86, fill=BLUE_L, radius=0.16)
            lines(box, [{"t": code, "s": 13, "b": True, "c": BLUE, "al": PP_ALIGN.CENTER}])
            box.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
            tx = self.box(slide, M + 7.76, y + 0.2, 3.95, 0.34,
                          [{"t": title, "s": 13.5, "b": True, "c": INK}])
            dx = self.box(slide, M + 7.76, y + 0.58, 3.95, 1.1,
                          [{"t": desc, "s": 11, "c": BODY}])
            Deck.group(anim,
                (c, FADE),
                (box, FLOAT),
                (tx, WIPE),
                (dx, FADE),
            )
            y += 1.95
        anim.add(left, FADE)
        anim.add(right, FADE)
        anim.flush()

    def slide_end(self) -> None:
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        anim = SlideAnim(slide)
        self.page += 1
        bg = self.rect(slide, 0, 0, SW, SH, fill=NAVY, shape=MSO_SHAPE.RECTANGLE)
        anim.add(bg, FADE)
        deco = self.rect(slide, 9.3, 3.6, 6.2, 6.2, fill=RGBColor(0x1B, 0x37, 0x6B),
                         shape=MSO_SHAPE.OVAL)
        anim.add(deco, FADE)
        bar = self.rect(slide, SW / 2 - 0.45, 2.5, 0.9, 0.09, fill=SKY,
                        shape=MSO_SHAPE.RECTANGLE)
        anim.add(bar, WIPE)
        t = self.box(slide, 0, 2.82, SW, 0.9,
                     [{"t": "汇报完毕，请老师批评指正", "s": 34, "b": True, "c": WHITE,
                       "al": PP_ALIGN.CENTER}])
        anim.add(t, WIPE)
        s = self.box(slide, 0, 3.86, SW, 0.5,
                     [{"t": "第 2 轮已完成 · 未阻塞项 · 可随时进入 R3 角色权限控制",
                       "s": 14, "b": True, "c": RGBColor(0xBF, 0xD7, 0xFF),
                       "al": PP_ALIGN.CENTER}])
        anim.add(s, FADE)
        q = self.box(slide, 0, 4.62, SW, 0.4,
                     [{"t": "Q & A", "s": 15, "b": True, "c": SKY, "al": PP_ALIGN.CENTER,
                       "mono": True}])
        anim.add(q, FADE)
        foot = self.box(slide, 0, 6.5, SW, 0.34,
                        [{"t": "学生成绩管理系统 · 软件工程课程实践 · 2026-09-23",
                          "s": 11, "c": RGBColor(0x7E, 0x9C, 0xD0), "al": PP_ALIGN.CENTER}])
        anim.add(foot, FADE)
        anim.flush()

    def build(self) -> None:
        self.cover()
        self.slide_agenda()
        self.slide_overview()
        self.slide_tech()
        self.slide_architecture()
        self.slide_er()
        self.slide_design_points()
        self.slide_r1()
        self.slide_r2_flow()
        self.slide_r2_security()
        self.slide_demo_login()
        self.slide_demo_home()
        self.slide_demo_roles()
        self.slide_demo_data()
        self.slide_test()
        self.slide_issues()
        self.slide_roadmap()
        self.slide_next()
        self.slide_end()
        self.add_notes()
        self.prs.save(OUTPUT)
        anim_count = 0
        clicks = 0
        for slide in self.prs.slides:
            anim_count += len(slide._element.findall(f".//{P}animEffect"))
            clicks += len(slide._element.findall(f".//{P}cTn[@nodeType='clickEffect']"))
        print(f"saved: {OUTPUT}")
        print(f"mode: {MODE}  slides: {len(self.prs.slides)}  "
              f"animations: {anim_count}  clicks: {clicks}")

    # ---------- 演讲者备注 ----------
    NOTES = {
        1: "开场：本系统是学生成绩管理系统，B/S 架构，用 Python + Flask 实现。"
           "今天汇报的是第 1、2 轮的进度：地基与用户认证。每页的出场动画是单击触发的，"
           "如果不想逐条点击，可放映时用“排练计时”自动播放，或直接使用自动播放版本。",
        2: "先给老师一个整体框架：我们按“计划 → 设计 → 实现与演示 → 验证与下一步”四步讲。",
        3: "强调一句：系统不开放自主注册，账号由管理员创建 —— 成绩系统不能让任何人自行注册。",
        4: "技术栈是课程未指定语言后我们自主选定的，依赖已经 pip freeze 冻结，"
           "保证换机器能复现。R1 的实测版本号都在这一页。",
        5: "重点讲应用工厂模式：create_app() 负责组装，蓝图按职责切分，"
           "后续 R4~R9 只是往这个骨架里加蓝图，不影响已有代码。",
        6: "6 张表的设计已冻结。说明外键方向：user 与 student / teacher 是一对一，"
           "student + course 组成 enrollment，成绩挂在 enrollment 上。",
        7: "这三个设计决定是验收最容易被追问的，先讲理由：enrollment 不是冗余、"
           "score 挂 enrollment、exam_type 支持多次考核。最后落到权限矩阵与行级校验。",
        8: "R1 的成果：12 条测试、97% 覆盖率、7 张表（含 alembic_version），"
           "种子数据幂等，口令全部是 scrypt 哈希。",
        9: "R2 的主线是认证流程五步。重点讲会话指纹：载荷是 user_id 加口令哈希的短摘要，"
           "这样改口令或停用账号后旧会话在下一次请求就失效，不需要额外的黑名单。",
        10: "这一页是安全细节。注意最后一条：现在只有 @login_required，"
            "按角色的 @role_required 和 403 页面是 R3 的任务 —— 我们不回避这个边界。",
        11: "演示：先看登录页，再故意输错口令，提示是同一句话，不泄露账号是否存在。",
        12: "演示：管理员登录后的首页。导航右侧显示姓名与角色徽标，首页表格是实时查库的，"
            "所以能直接看到 6 张表的记录数。",
        13: "演示：三种角色的导航不同。但要说明：这只是按角色渲染菜单，"
            "服务端鉴权还没做，直接敲 URL 仍然能访问，R3 必须补上。",
        14: "证据页：建表走 Alembic，db current 显示 fba8e95c58f8 (head)；"
            "测试里有一条专门比对 ORM 模型与迁移脚本，忘记生成迁移会直接失败。",
        15: "测试：47 条全绿，覆盖率 98%，auth.py / decorators.py / models.py 都是 100%。"
            "右侧是重点覆盖的边界。注意 R11 要求的是权限矩阵与边界覆盖，当前覆盖率不能替代它。",
        16: "复盘：三个问题都出在工程细节上 —— 模板重构、CSRF token 的注入位置、"
            "受限环境下的临时目录。解决方式都记在 docs/验收记录.md 里，可直接作为报告素材。",
        17: "进度对照：2 / 12 完成。每轮结束系统都是可运行、可演示、测试全绿，"
            "所以计划可以在任意一轮结束，也可以在中间插入新轮次。",
        18: "下一步是 R3 角色权限控制：补 @role_required、403 页面、权限矩阵测试。"
            "重点仍然是行级校验。R3 之后进入 R4~R5 的网页 CRUD。",
        19: "结束语，请老师提问。",
    }

    def add_notes(self) -> None:
        for i, slide in enumerate(self.prs.slides, 1):
            text = self.NOTES.get(i, "")
            if i == 1 and MODE == "auto":
                text = "【自动播放版】所有元素已改为自动依次出现，换片为淡入；" \
                       "放映时无需点击。若需要逐条控制，请使用单击版文件。" + text
            if text:
                slide.notes_slide.notes_text_frame.text = text


if __name__ == "__main__":
    Deck().build()
