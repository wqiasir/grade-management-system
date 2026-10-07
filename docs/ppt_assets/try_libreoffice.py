# -*- coding: utf-8 -*-
"""用 LibreOffice（若已安装）把 pptx 转成 PDF，用于交叉验证文件是否被第三方渲染器接受。"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import tempfile

ROOT = r"D:\作业\软件工程课程实践"
#: 成品已按汇报次数归档到 工作目录根/PPT/第1次/
PPT_DIR = os.path.join(ROOT, "PPT", "第1次")
TARGETS = [
    os.path.join(PPT_DIR, "软件工程课程实践_进度总结_R1-R2.pptx"),
    os.path.join(PPT_DIR, "软件工程课程实践_进度总结_R1-R2_自动播放版.pptx"),
]


def find_soffice() -> str | None:
    for pat in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        r"C:\Program Files\WPS Office\*\office6\wps.exe",
    ):
        hits = glob.glob(pat)
        if hits:
            return hits[0]
    return shutil.which("soffice") or shutil.which("libreoffice")


def main() -> None:
    exe = find_soffice()
    if not exe:
        print("LibreOffice / WPS 未安装，跳过")
        return
    print("found:", exe)
    out = tempfile.mkdtemp(prefix="ppt2pdf_")
    for t in TARGETS:
        if not os.path.exists(t):
            print("missing:", t)
            continue
        cmd = [exe, "--headless", "--norestore", "--convert-to", "pdf", "--outdir", out, t]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        print(os.path.basename(t), "->", r.returncode, r.stdout.strip()[:200], r.stderr.strip()[:200])
    for f in glob.glob(os.path.join(out, "*.pdf")):
        print("pdf:", f, os.path.getsize(f), "bytes")


if __name__ == "__main__":
    main()
