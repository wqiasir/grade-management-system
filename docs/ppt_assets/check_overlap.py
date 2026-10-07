# -*- coding: utf-8 -*-
"""只列出同一页里明显重叠的形状对（帮助人工判断布局问题）。"""

from __future__ import annotations

import os
import zipfile

from lxml import etree

HERE = os.path.dirname(os.path.abspath(__file__))
#: 成品已按汇报次数归档到 工作目录根/PPT/第1次/
PPTX = os.path.abspath(os.path.join(HERE, "..", "..", "..", "PPT", "第1次",
                                    "软件工程课程实践_进度总结_R1-R2.pptx"))
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
EMU = 914400

# 有意为之的"叠放"：大背景块/装饰圆/卡片底 与 其上的文字
BACKGROUNDY = ("Rectangle", "Oval", "Rounded Rectangle")


def collect(root):
    out = []
    for el in root.find(f"{P}cSld/{P}spTree"):
        kind = etree.QName(el).localname
        if kind not in ("sp", "pic", "graphicFrame"):
            continue
        cnv = el.find(f".//{P}cNvPr")
        name = cnv.get("name") if cnv is not None else "?"
        xfrm = el.find(f".//{A}xfrm")
        if xfrm is None:
            continue
        off, ext = xfrm.find(f"{A}off"), xfrm.find(f"{A}ext")
        if off is None or ext is None:
            continue
        has_text = el.find(f".//{A}r/{A}t") is not None
        out.append({
            "name": name,
            "kind": kind,
            "x": int(off.get("x")) / EMU, "y": int(off.get("y")) / EMU,
            "w": int(ext.get("cx")) / EMU, "h": int(ext.get("cy")) / EMU,
            "text": has_text,
        })
    return out


def main() -> None:
    z = zipfile.ZipFile(PPTX)
    names = sorted([n for n in z.namelist() if n.startswith("ppt/slides/slide")],
                   key=lambda n: int("".join(c for c in os.path.basename(n) if c.isdigit())))
    total = 0
    for idx, n in enumerate(names, 1):
        shapes = collect(etree.fromstring(z.read(n)))
        issues = []
        for i, a in enumerate(shapes):
            for b in shapes[i + 1:]:
                ox = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
                oy = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
                if ox <= 0.04 or oy <= 0.04:
                    continue
                area = ox * oy
                # 背景板压文字属正常层叠
                if not (a["text"] and b["text"]):
                    continue
                if area > 0.05:
                    issues.append((area, a, b))
        if issues:
            print(f"\n=== slide {idx:02d} 文本形状重叠 {len(issues)} 处 ===")
            for area, a, b in sorted(issues, key=lambda t: -t[0])[:6]:
                print(f"  {area:.2f}in2  {a['name']}({a['x']:.2f},{a['y']:.2f},{a['w']:.2f}x{a['h']:.2f})"
                      f"  x  {b['name']}({b['x']:.2f},{b['y']:.2f},{b['w']:.2f}x{b['h']:.2f})")
        total += len(issues)
    print(f"\n合计 {total} 处")


if __name__ == "__main__":
    main()
