# -*- coding: utf-8 -*-
"""交付前校验：把每页 PPT 渲染成 PNG，并估算文本是否溢出形状。

渲染方式优先用 PowerPoint COM 导出；不可用时退化为"用 PIL 按 XML 坐标重绘"，
足以检查布局与文字是否越界。
"""

from __future__ import annotations

import os
import shutil
import sys
import zipfile
from typing import Iterator

from lxml import etree
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "render")
#: 成品已按汇报次数归档到 工作目录根/PPT/第1次/
PPTX = os.path.abspath(os.path.join(HERE, "..", "..", "..", "PPT", "第1次",
                                    "软件工程课程实践_进度总结_R1-R2.pptx"))

P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
EMU_IN = 914400
SCALE = 110  # 每英寸像素


def cjk_width(ch: str) -> float:
    o = ord(ch)
    if o < 0x2E80:
        return 0.55
    if ch in "，。、；：（）《》“”！？·—…":
        return 1.0
    return 1.0


def text_width(s: str, pt: float) -> float:
    return sum(cjk_width(c) for c in s) * pt


FONT_CACHE: dict[tuple[float, bool], ImageFont.FreeTypeFont] = {}


def font_for(size_pt: float, mono: bool) -> ImageFont.FreeTypeFont:
    key = (round(size_pt, 1), mono)
    if key in FONT_CACHE:
        return FONT_CACHE[key]
    px = max(8, int(round(size_pt * (SCALE / 72.0))))
    candidates = ("consola.ttf", "cour.ttf") if mono else ("msyh.ttc", "msyhl.ttc", "simhei.ttf")
    f = None
    for name in candidates:
        try:
            f = ImageFont.truetype(name, px)
            break
        except Exception:
            continue
    if f is None:
        f = ImageFont.load_default()
    FONT_CACHE[key] = f
    return f


def fill_for(kind: str, has_text: bool) -> tuple[int, int, int]:
    if has_text:
        return (252, 252, 253)
    return (238, 242, 248)


class Shape:
    def __init__(self, el) -> None:
        self.el = el
        self.kind = etree.QName(el).localname
        self.id = int(el.find(f"{P}nvSpPr/{P}cNvPr").get("id")) if el.find(
            f"{P}nvSpPr/{P}cNvPr") is not None else -1
        cnv = None
        for tag in ("nvSpPr", "nvPicPr", "nvGraphicFramePr", "nvCxnSpPr"):
            node = el.find(f"{P}{tag}/{P}cNvPr")
            if node is not None:
                cnv = node
                break
        self.name = cnv.get("name") if cnv is not None else "?"
        xfrm = el.find(f".//{A}xfrm")
        self.x = self.y = self.w = self.h = 0.0
        if xfrm is not None:
            off, ext = xfrm.find(f"{A}off"), xfrm.find(f"{A}ext")
            if off is not None:
                self.x = int(off.get("x")) / EMU_IN
                self.y = int(off.get("y")) / EMU_IN
            if ext is not None:
                self.w = int(ext.get("cx")) / EMU_IN
                self.h = int(ext.get("cy")) / EMU_IN
        self.paragraphs: list[list[tuple[str, float, bool, bool]]] = []
        tx = el.find(f".//{A}txBody")
        if tx is not None:
            for p in tx.findall(f"{A}p"):
                runs = []
                for r in p.findall(f"{A}r"):
                    t = r.find(f"{A}t")
                    if t is None or not t.text:
                        continue
                    rpr = r.find(f"{A}rPr")
                    size = 18.0
                    bold = mono = False
                    if rpr is not None:
                        if rpr.get("sz"):
                            size = int(rpr.get("sz")) / 100.0
                        bold = rpr.get("b") == "1"
                        for tag in ("latin", "ea"):
                            f = rpr.find(f"{A}{tag}")
                            if f is not None and (f.get("typeface") or "").lower().startswith("consol"):
                                mono = True
                    runs.append((t.text, size, bold, mono))
                self.paragraphs.append(runs)


def slide_shapes(path: str) -> Iterator[tuple[int, list[Shape], float, float]]:
    z = zipfile.ZipFile(path)
    pres = etree.fromstring(z.read("ppt/presentation.xml"))
    size = pres.find(f"{P}sldSz")
    sw = int(size.get("cx")) / EMU_IN
    sh = int(size.get("cy")) / EMU_IN
    names = sorted(
        [n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")],
        key=lambda n: int("".join(ch for ch in os.path.basename(n) if ch.isdigit())),
    )
    for idx, n in enumerate(names, 1):
        root = etree.fromstring(z.read(n))
        spTree = root.find(f"{P}cSld/{P}spTree")
        shapes = []
        for el in spTree:
            if etree.QName(el).localname in ("sp", "pic", "graphicFrame", "cxnSp"):
                s = Shape(el)
                if s.w > 0:
                    shapes.append(s)
        yield idx, shapes, sw, sh


def validate_package(path: str) -> list[str]:
    """结构性校验：动画 spid 是否都能对上形状、每页是否可解析、关系是否齐全。"""
    errs: list[str] = []
    z = zipfile.ZipFile(path)
    bad = z.testzip()
    if bad:
        errs.append(f"zip 损坏: {bad}")

    pres = etree.fromstring(z.read("ppt/presentation.xml"))
    rels = etree.fromstring(z.read("ppt/_rels/presentation.xml.rels"))
    rel_ids = {r.get("Id") for r in rels}
    slide_ids = [s.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                 for s in pres.find(f"{P}sldIdLst")]
    for rid in slide_ids:
        if rid not in rel_ids:
            errs.append(f"presentation.xml 引用了不存在的关系 {rid}")

    names = sorted([n for n in z.namelist() if n.startswith("ppt/slides/slide")
                    and n.endswith(".xml")],
                   key=lambda n: int("".join(c for c in os.path.basename(n) if c.isdigit())))
    for n in names:
        idx = int("".join(c for c in os.path.basename(n) if c.isdigit()))
        root = etree.fromstring(z.read(n))
        ids = {int(e.get("id")) for e in root.findall(f".//{P}cNvPr")}
        timing = root.find(f"{P}timing")
        if timing is None:
            errs.append(f"slide{idx}: 没有 p:timing（无出场动画）")
            continue
        spids = [int(e.get("spid")) for e in timing.findall(f".//{P}spTgt")]
        missing = sorted({s for s in spids if s not in ids})
        if missing:
            errs.append(f"slide{idx}: 动画引用了不存在的形状 id {missing}")
        ctns = timing.findall(f".//{P}cTn")
        cids = [c.get("id") for c in ctns]
        if len(cids) != len(set(cids)):
            errs.append(f"slide{idx}: cTn id 重复")
        if timing.find(f".//{P}cTn[@nodeType='tmRoot']") is None:
            errs.append(f"slide{idx}: 缺少 tmRoot 节点")
        if timing.find(f".//{P}cTn[@nodeType='mainSeq']") is None:
            errs.append(f"slide{idx}: 缺少 mainSeq 节点")
        nrels = f"ppt/slides/_rels/{os.path.basename(n)}.rels"
        if nrels in z.namelist():
            etree.fromstring(z.read(nrels))
    return errs


def wrap_runs(runs, avail_px: int) -> list[list[tuple[str, float, bool, bool]]]:
    """按可用宽度折行；runs = [(text, size_pt, bold, mono), ...]，返回按行分组的 runs。"""
    lines: list[list[tuple[str, float, bool, bool]]] = []
    cur: list[tuple[str, float, bool, bool]] = []
    cur_w = 0.0
    for text, sz, bold, mono in runs:
        f = font_for(sz, mono)
        chunk = ""
        for ch in text:
            w = f.getlength(ch)
            if cur_w + w > avail_px and (cur or chunk):
                if chunk:
                    cur.append((chunk, sz, bold, mono))
                lines.append(cur)
                cur, cur_w, chunk = [], 0.0, ""
            chunk += ch
            cur_w += w
        if chunk:
            cur.append((chunk, sz, bold, mono))
    if cur:
        lines.append(cur)
    return lines or [[]]


def render(path: str, with_text: bool = True) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    warnings: list[str] = []
    for idx, shapes, sw, sh in slide_shapes(path):
        img = Image.new("RGB", (int(sw * SCALE), int(sh * SCALE)), (255, 255, 255))
        d = ImageDraw.Draw(img)
        for s in shapes:
            box = [s.x * SCALE, s.y * SCALE, (s.x + s.w) * SCALE, (s.y + s.h) * SCALE]
            if box[0] < -2 or box[1] < -2 or box[2] > sw * SCALE + 2 or box[3] > sh * SCALE + 2:
                if s.kind not in ("cxnSp",):
                    warnings.append(
                        f"slide{idx:02d} 超出页面: {s.name} "
                        f"({s.x:.2f},{s.y:.2f},{s.w:.2f},{s.h:.2f})"
                    )
            if s.kind == "cxnSp":
                d.line(box, fill=(120, 175, 235), width=2)
                continue
            has_text = bool(s.paragraphs)
            d.rectangle(box, outline=(150, 165, 195) if has_text else None,
                        width=1 if has_text else 0,
                        fill=None if has_text else fill_for(s.kind, False))
            if s.kind == "pic":
                d.rectangle(box, fill=(206, 219, 240), outline=(140, 160, 195), width=1)
                d.line([box[0], box[1], box[2], box[3]], fill=(150, 170, 205), width=1)
                d.line([box[0], box[3], box[2], box[1]], fill=(150, 170, 205), width=1)
                continue
            if not has_text or not with_text:
                continue

            pad_l = 0.14 * SCALE
            avail = max(20, s.w * SCALE - 2 * pad_l)
            y = s.y * SCALE + 0.08 * SCALE
            max_pt = max((max(r[1] for r in rs) for rs in s.paragraphs if rs), default=9.0)
            for runs in s.paragraphs:
                if not runs:
                    y += 0.16 * SCALE
                    continue
                size = max(r[1] for r in runs)
                lh = size * 1.42 * (SCALE / 72.0)
                for line in wrap_runs(runs, avail):
                    x = s.x * SCALE + pad_l
                    for text, sz, bold, mono in line:
                        f = font_for(sz, mono)
                        if y + lh > (s.y + s.h) * SCALE + lh:  # 溢出形状
                            break
                        d.text((x, y + (lh - sz * (SCALE / 72.0)) * 0.25), text,
                               font=f, fill=(70, 82, 100) if not bold else (32, 44, 66))
                        x += f.getlength(text)
                    y += lh
            need = (y - s.y * SCALE - 0.08 * SCALE) / SCALE
            if need > s.h + 0.03:
                warnings.append(
                    f"slide{idx:02d} 文本可能溢出: {s.name} 需要 {need:.2f}in / 空间 {s.h:.2f}in "
                    f"(w={s.w:.2f}, 最大字号 {max_pt:.1f}pt) :: "
                    f"{''.join(r[0] for r in s.paragraphs[0])[:30]}"
                )
        img.save(os.path.join(OUT_DIR, f"slide{idx:02d}.png"))
    print(f"rendered {idx} slides -> {OUT_DIR}")
    if warnings:
        print(f"\n!! {len(warnings)} 条告警：")
        for w in warnings:
            print("  -", w)
    else:
        print("no overflow warnings")


def try_powerpoint(path: str) -> bool:
    try:
        import win32com.client as win32
    except Exception:
        return False
    try:
        app = win32.DispatchEx("PowerPoint.Application")
        pres = app.Presentations.Open(path, ReadOnly=True, Untitled=False, WithWindow=False)
        app.ActivePresentation.Export(OUT_DIR, "PNG", 1600, 900)
        pres.Close()
        app.Quit()
        return True
    except Exception as exc:
        print("powerpoint export unavailable:", exc)
        return False


if __name__ == "__main__":
    if not os.path.exists(PPTX):
        sys.exit(f"missing pptx: {PPTX}")
    targets = [PPTX]
    auto = os.path.join(os.path.dirname(PPTX),
                        "软件工程课程实践_进度总结_R1-R2_自动播放版.pptx")
    if os.path.exists(auto):
        targets.append(auto)
    for t in targets:
        print(f"\n--- {os.path.basename(t)} ---")
        errs = validate_package(t)
        print(f"结构校验：{'通过（无问题）' if not errs else str(len(errs)) + ' 个问题'}")
        for e in errs:
            print("  -", e)
    if "--com" in sys.argv and try_powerpoint(PPTX):
        print("exported via PowerPoint ->", OUT_DIR)
    else:
        render(PPTX)
