# -*- coding: utf-8 -*-
"""单变量对照实验：找出 PowerPoint 拒绝打开动画 pptx 的真正原因。

用 python-pptx 生成结构完全相同、只改一个属性的 slide1.xml，逐个用
PowerPoint COM 打开，记录成功/失败。全程使用独立临时文件，不改动交付物。
"""

from __future__ import annotations

import copy
import os
import tempfile

from lxml import etree
from pptx import Presentation
from pptx.util import Inches

P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_probe")
os.makedirs(OUT, exist_ok=True)


def build_base(path: str) -> None:
    """两形状 + 最小 timing（单层 par，无中间层）。"""
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    ids = []
    for i, txt in enumerate(("第一个形状", "第二个形状")):
        box = slide.shapes.add_textbox(Inches(1), Inches(1 + i * 1.4), Inches(8), Inches(1))
        box.text_frame.text = txt
        ids.append(box.shape_id)
    prs.save(path)


def inject(path: str, *, prev_ac: str = "enabled", seq_next_ac: str = "seek",
           seq_concurrent: str = "1", kids: int = 2, mid_level: bool = False) -> None:
    """往 slide1.xml 注入 timing。所有可变点都通过参数控制。"""
    from pptx import Presentation as P2

    prs = P2(path)
    slide = prs.slides[0]
    ids = [sh.shape_id for sh in slide.shapes]
    root = slide._element
    timing = etree.SubElement(root, P + "timing")
    tn = etree.SubElement(timing, P + "tnLst")
    par = etree.SubElement(tn, P + "par")
    ctn = etree.SubElement(par, P + "cTn")
    ctn.set("id", "1")
    ctn.set("dur", "indefinite")
    ctn.set("restart", "never")
    ctn.set("nodeType", "tmRoot")
    c1 = etree.SubElement(ctn, P + "childTnLst")
    seq = etree.SubElement(c1, P + "seq")
    if seq_concurrent is not None:
        seq.set("concurrent", seq_concurrent)
    if prev_ac is not None:
        seq.set("prevAc", prev_ac)
    if seq_next_ac is not None:
        seq.set("nextAc", seq_next_ac)
    sctn = etree.SubElement(seq, P + "cTn")
    sctn.set("id", "2")
    sctn.set("dur", "indefinite")
    sctn.set("nodeType", "mainSeq")
    main = etree.SubElement(sctn, P + "childTnLst")

    nid = 3
    for i in range(kids):
        sid = ids[i]
        if mid_level:
            # 三层：clickEffect 包裹 withEffect
            outer = etree.SubElement(main, P + "par")
            octn = etree.SubElement(outer, P + "cTn")
            octn.set("id", str(nid)); nid += 1
            octn.set("fill", "hold")
            octn.set("nodeType", "clickEffect")
            ost = etree.SubElement(octn, P + "stCondLst")
            oc = etree.SubElement(ost, P + "cond"); oc.set("delay", "0")
            och = etree.SubElement(octn, P + "childTnLst")
            target_ctn = etree.SubElement(och, P + "par")
            tctn = etree.SubElement(target_ctn, P + "cTn")
            tctn.set("id", str(nid)); nid += 1
            tctn.set("fill", "hold")
            tctn.set("nodeType", "withEffect")
            inner = etree.SubElement(tctn, P + "childTnLst")
        else:
            inner = main
        par2 = etree.SubElement(inner, P + "par")
        ctn2 = etree.SubElement(par2, P + "cTn")
        ctn2.set("id", str(nid)); nid += 1
        ctn2.set("presetID", "10")
        ctn2.set("presetClass", "entr")
        ctn2.set("presetSubtype", "0")
        ctn2.set("fill", "hold")
        ctn2.set("grpId", "0")
        ctn2.set("nodeType", "clickEffect")
        st = etree.SubElement(ctn2, P + "stCondLst")
        c = etree.SubElement(st, P + "cond"); c.set("delay", "0")
        ch = etree.SubElement(ctn2, P + "childTnLst")
        # set
        se = etree.SubElement(ch, P + "set")
        cb = etree.SubElement(se, P + "cBhvr")
        bctn = etree.SubElement(cb, P + "cTn")
        bctn.set("id", str(nid)); nid += 1
        bctn.set("dur", "1"); bctn.set("fill", "hold")
        bst = etree.SubElement(bctn, P + "stCondLst")
        bc = etree.SubElement(bst, P + "cond"); bc.set("delay", "0")
        tgt = etree.SubElement(cb, P + "tgtEl")
        sp = etree.SubElement(tgt, P + "spTgt"); sp.set("spid", str(sid))
        anl = etree.SubElement(cb, P + "attrNameLst")
        an = etree.SubElement(anl, P + "attrName"); an.text = "style.visibility"
        # animEffect
        ae = etree.SubElement(ch, P + "animEffect")
        ae.set("transition", "in"); ae.set("filter", "fade")
        acb = etree.SubElement(ae, P + "cBhvr")
        actn = etree.SubElement(acb, P + "cTn")
        actn.set("id", str(nid)); nid += 1
        actn.set("dur", "400")
        atgt = etree.SubElement(acb, P + "tgtEl")
        asp = etree.SubElement(atgt, P + "spTgt"); asp.set("spid", str(sid))
    prs.save(path)


def try_open(path: str) -> str:
    """返回 'OK' 或错误描述。"""
    try:
        import win32com.client as win32
    except Exception as exc:
        return f"no-pywin32({exc})"
    app = None
    try:
        app = win32.DispatchEx("PowerPoint.Application")
        pres = app.Presentations.Open(os.path.abspath(path), ReadOnly=True,
                                      Untitled=False, WithWindow=False)
        info = f"OK slides={pres.Slides.Count}"
        try:
            seq = pres.Slides(1).TimeLine.MainSequence
            info += f" mainSeq={seq.Count}"
            for j in range(1, seq.Count + 1):
                e = seq.Item(j)
                info += f" [{j}:{e.Shape.Name},eff={e.EffectType},trig={e.Timing.TriggerType}]"
        except Exception as exc:
            info += f" (读动画失败: {exc})"
        pres.Close()
        return info
    except Exception as exc:
        return f"FAIL {exc}"
    finally:
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass


def main() -> None:
    base = os.path.join(OUT, "base.pptx")
    build_base(base)
    cases = [
        ("A 基准：有 prevAc=enabled（当前交付物的写法）", dict(prev_ac="enabled")),
        ("B 删掉 prevAc", dict(prev_ac=None)),
        ("C prevAc=seek", dict(prev_ac="seek")),
        ("D 有 prevAc + nextAc=seek", dict(prev_ac="enabled", seq_next_ac="seek")),
        ("E 无 prevAc + 无 nextAc", dict(prev_ac=None, seq_next_ac=None)),
        ("F 无 prevAc + 三层结构(withEffect)", dict(prev_ac=None, mid_level=True)),
        ("G 有 prevAc + 三层结构", dict(prev_ac="enabled", mid_level=True)),
        ("H 无 prevAc + concurrent=1 去掉", dict(prev_ac=None, seq_concurrent=None)),
        ("I 有 prevAc + concurrent 去掉", dict(prev_ac="enabled", seq_concurrent=None)),
    ]
    for label, kw in cases:
        p = os.path.join(OUT, "case.pptx")
        if os.path.exists(p):
            os.remove(p)
        build_base(p)
        inject(p, **kw)
        print(f"{label}\n    -> {try_open(p)}")


if __name__ == "__main__":
    main()
