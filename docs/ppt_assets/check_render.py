# -*- coding: utf-8 -*-
"""对 verify_ppt.py 渲染出的预览图做版面健全性检查。

检查项：
1. 内容区（1.80~6.40 英寸）是否有足够的"墨迹"，避免出现空页；
2. 页脚带（6.45~7.4 英寸）是否只有页脚与页码，没有正文误入；
3. 页面四周是否出现贴边文字（说明元素溢出页面）。
"""

from __future__ import annotations

import glob
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
RENDER = os.path.join(HERE, "render")
DPI = 110  # 与 verify_ppt.SCALE 一致


def ink_rows(im: Image.Image, thresh: int = 240):
    w, h = im.size
    px = im.load()
    rows = []
    for y in range(h):
        c = 0
        for x in range(0, w, 3):
            r, g, b = px[x, y][:3]
            if r < thresh or g < thresh or b < thresh:
                c += 1
        rows.append(c)
    return rows


def main() -> None:
    files = sorted(glob.glob(os.path.join(RENDER, "slide*.png")))
    if not files:
        print("还没有预览图，请先运行 verify_ppt.py")
        return
    problems = []
    for f in files:
        name = os.path.basename(f)
        im = Image.open(f).convert("RGB")
        w, h = im.size
        rows = ink_rows(im)
        total = sum(rows)
        content = sum(rows[int(1.78 * DPI):int(6.44 * DPI)])
        footer = sum(rows[int(6.46 * DPI):])
        # 贴边墨迹：第一列/最后一列有内容
        px = im.load()
        edge = 0
        for y in range(h):
            for x in (0, 1, w - 2, w - 1):
                r, g, b = px[x, y][:3]
                if r < 240 and (y < 60 or y > h - 60):
                    edge += 1
        flag = []
        if content < w * 40:
            flag.append(f"内容区偏空(content ink={content})")
        if footer > w * 120:
            flag.append(f"页脚带墨迹偏多(footer ink={footer})")
        if edge > 4:
            flag.append(f"贴边墨迹 {edge} 像素")
        status = "；".join(flag) if flag else "OK"
        if flag:
            problems.append((name, status))
        print(f"{name}: size={w}x{h} 总墨迹={total} 内容区={content} 页脚带={footer} -> {status}")
    print(f"\n有问题 {len(problems)} 页 / 共 {len(files)} 页")


if __name__ == "__main__":
    main()
