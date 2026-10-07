# -*- coding: utf-8 -*-
"""把浏览器截图裁成 PPT 用的展示图（去空白、加圆角描边投影）。

产物在 ``docs/ppt_assets/out/``。原始截图为 2 倍设备像素（1370 CSS 宽）。
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)

RADIUS = 10
M = 22  # 投影外扩

#: (源文件, 输出名, 裁剪下边界[设备像素], 是否投影)
JOBS: list[tuple[str, str, int, bool]] = [
    ("04_home_admin.png", "home_admin_full.png", 1994, True),
    ("02_login.png", "login_full.png", 1868, True),
    ("03_login_error.png", "login_error_full.png", 2034, True),
    # 无投影版本：用于需要精确贴合卡片的内容页
    ("04_home_admin.png", "home_admin_plain.png", 1994, False),
    ("07_logout.png", "logout_top.png", 1060, False),
    # 三栏对比：导航 + "当前登录状态"卡片，三种角色共用同一裁剪区间
    ("04_home_admin.png", "role_admin.png", 1392, False),
    ("05_home_teacher.png", "role_teacher.png", 1392, False),
    ("06_home_student.png", "role_student.png", 1392, False),
    # 首页"数据表"区块：迁移与建表的证据
    ("04_home_admin.png", "tables.png", 1830, False),
]


def rounded(im: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, im.size[0] - 1, im.size[1] - 1], radius, fill=255
    )
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    out.paste(im.convert("RGBA"), (0, 0), mask)
    return out


def shadow(img: Image.Image, dy: int = 6, blur: int = 9, alpha: int = 74) -> Image.Image:
    w, h = img.size
    canvas = Image.new("RGBA", (w + 2 * M, h + 2 * M), (0, 0, 0, 0))
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle(
        [M, M + dy, M + w, M + h + dy], RADIUS, fill=(15, 32, 66, alpha)
    )
    canvas = Image.alpha_composite(canvas, sh.filter(ImageFilter.GaussianBlur(blur)))
    canvas.alpha_composite(rounded(img, RADIUS), (M, M))
    return canvas


def plain(img: Image.Image, border: bool = True) -> Image.Image:
    """不投影版本：可选 1px 描边，用于三栏并排的小图。"""
    w, h = img.size
    pad = 3 if border else 0
    canvas = Image.new("RGB", (w + 2 * pad, h + 2 * pad), (255, 255, 255))
    if border:
        d = ImageDraw.Draw(canvas)
        d.rectangle([0, 0, canvas.size[0] - 1, canvas.size[1] - 1], outline=(206, 214, 228))
    canvas.paste(img.convert("RGB"), (pad, pad))
    return canvas


def main() -> None:
    for src, dst, bottom, use_shadow in JOBS:
        path = os.path.join(HERE, src)
        if not os.path.exists(path):
            print("skip (missing):", src)
            continue
        im = Image.open(path).convert("RGB")
        w, h = im.size
        crop = im.crop((0, 0, w, min(bottom, h)))
        result = shadow(crop) if use_shadow else plain(crop)
        out_path = os.path.join(OUT, dst)
        result.convert("RGB").save(out_path, "PNG", optimize=True)
        css = (crop.size[0] // 2, crop.size[1] // 2)
        print(f"{src} -> {dst}  crop_css={css[0]}x{css[1]}  out={result.size}")


if __name__ == "__main__":
    main()
