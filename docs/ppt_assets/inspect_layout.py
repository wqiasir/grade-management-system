# -*- coding: utf-8 -*-
"""粗查每页形状的垂直/水平排布（重叠与越界）。"""

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


def main() -> None:
    z = zipfile.ZipFile(PPTX)
    names = sorted([n for n in z.namelist() if n.startswith("ppt/slides/slide")],
                   key=lambda n: int("".join(c for c in os.path.basename(n) if c.isdigit())))
    for idx, n in enumerate(names, 1):
        root = etree.fromstring(z.read(n))
        rows = []
        for el in root.find(f"{P}cSld/{P}spTree"):
            kind = etree.QName(el).localname
            if kind not in ("sp", "pic", "graphicFrame"):
                continue
            xfrm = el.find(f".//{A}xfrm")
            if xfrm is None:
                continue
            off, ext = xfrm.find(f"{A}off"), xfrm.find(f"{A}ext")
            if off is None or ext is None:
                continue
            x, y = int(off.get("x")) / EMU, int(off.get("y")) / EMU
            w, h = int(ext.get("cx")) / EMU, int(ext.get("cy")) / EMU
            # 取第一段文字做标注
            t = ""
            tx = el.find(f".//{A}txBody")
            if tx is not None:
                te = tx.find(f".//{A}t")
                t = (te.text or "")[:22] if te is not None else ""
            rows.append((y, x, w, h, t))
        print(f"\n=== slide {idx:02d} ===")
        for y, x, w, h, t in sorted(rows):
            flag = ""
            if y < -0.01 or y + h > 7.52 or x < -0.01 or x + w > 13.35:
                flag = "  <== 出界"
            print(f"  y={y:5.2f} h={h:4.2f} x={x:5.2f} w={w:5.2f}  {t!r}{flag}")


if __name__ == "__main__":
    main()
