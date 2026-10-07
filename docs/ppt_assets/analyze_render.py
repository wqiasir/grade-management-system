# -*- coding: utf-8 -*-
"""分析 PowerPoint 自己导出的幻灯片 PNG，确认版面无异常。

这些图是 PowerPoint 真实渲染结果，所以可以直接判断：
- 内容包围盒是否越出页面；
- 是否出现大片空白（内容丢失）；
- 深蓝底页面（封面/结束页）是否为全出血背景。
"""

from __future__ import annotations

import glob
import os
from collections import Counter

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, "render_powerpoint")


def main() -> None:
    files = sorted(glob.glob(os.path.join(DIR, "*.PNG")) + glob.glob(os.path.join(DIR, "*.png")),
                   key=lambda p: int("".join(c for c in os.path.basename(p) if c.isdigit())))
    if not files:
        print("没有导出的图片")
        return
    for f in files:
        im = Image.open(f).convert("RGB")
        w, h = im.size
        px = im.load()
        bg = Counter(px[x, y] for x in range(0, w, 9) for y in range(0, h, 9)).most_common(1)[0][0]
        # 内容包围盒（与主导色不同即视为内容）
        def diff(p):
            return abs(p[0] - bg[0]) + abs(p[1] - bg[1]) + abs(p[2] - bg[2]) > 24

        minx, miny, maxx, maxy = w, h, -1, -1
        ink = 0
        for y in range(0, h, 2):
            for x in range(0, w, 2):
                if diff(px[x, y]):
                    ink += 1
                    if x < minx:
                        minx = x
                    if x > maxx:
                        maxx = x
                    if y < miny:
                        miny = y
                    if y > maxy:
                        maxy = y
        coverage = ink * 4 / (w * h)
        edge = "无"
        if minx <= 1 or miny <= 1 or maxx >= w - 2 or maxy >= h - 2:
            edge = "内容贴边"
        name = os.path.basename(f)
        print(f"{name:>16}: {w}x{h} 主导色={bg} 内容包围盒=({minx},{miny})-({maxx},{maxy}) "
              f"覆盖率={coverage:.1%} 贴边={edge}")


if __name__ == "__main__":
    main()
