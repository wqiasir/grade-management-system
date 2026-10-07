# -*- coding: utf-8 -*-
"""交付物终检：用 PowerPoint COM 打开成品 pptx，逐页读回出场动画。

这一步是最终验收：能打开 + MainSequence 数量正确 + 每项效果类型/触发方式读得出来。
"""

from __future__ import annotations

import os
import sys

import win32com.client as win32

ROOT = r"D:\作业\软件工程课程实践"
#: 成品已按汇报次数归档到 工作目录根/PPT/第1次/
PPT_DIR = os.path.join(ROOT, "PPT", "第1次")
FILES = [
    ("单击版", os.path.join(PPT_DIR, "软件工程课程实践_进度总结_R1-R2.pptx")),
    ("自动播放版", os.path.join(PPT_DIR, "软件工程课程实践_进度总结_R1-R2_自动播放版.pptx")),
]

TRIGGER_NAME = {1: "单击", 2: "与上一动画同时", 3: "上一动画之后"}


def check(app, label: str, path: str) -> bool:
    print(f"\n=== {label}：{os.path.basename(path)} ===")
    total = 0
    ok = True
    try:
        pres = app.Presentations.Open(os.path.abspath(path), ReadOnly=True,
                                     Untitled=False, WithWindow=False)
    except Exception as exc:
        print(f"  !! 打开失败: {exc}")
        return False
    try:
        n = pres.Slides.Count
        print(f"  打开成功，共 {n} 页")
        for i in range(1, n + 1):
            sl = pres.Slides(i)
            try:
                seq = sl.TimeLine.MainSequence
                cnt = seq.Count
            except Exception as exc:
                print(f"  slide{i:02d}: 读动画失败 {exc}")
                ok = False
                continue
            total += cnt
            detail = []
            bad = 0
            for j in range(1, cnt + 1):
                try:
                    e = seq.Item(j)
                    trig = e.Timing.TriggerType
                    dur = e.Timing.Duration
                    detail.append(f"{e.Shape.Name[:12]}/{e.EffectType}/{TRIGGER_NAME.get(trig, trig)}/{dur}s")
                except Exception as exc:
                    bad += 1
                    detail.append(f"!!读取失败({exc})")
            if bad:
                ok = False
            print(f"  slide{i:02d}: {cnt:2d} 个动画"
                  + ("  <== 有读取失败项" if bad else "")
                  + ("   " + "; ".join(detail[:3]) + (" …" if cnt > 3 else "") if cnt else ""))
        print(f"  合计 {total} 个动画")
        # 往返保存后再看一次（验证动画能被 PowerPoint 持久化）
        rt = os.path.join(os.path.dirname(path), "_rt_check.pptx")
        if os.path.exists(rt):
            os.remove(rt)
        pres.SaveAs(rt)
        pres.Close()
        pres2 = app.Presentations.Open(os.path.abspath(rt), ReadOnly=True,
                                       Untitled=False, WithWindow=False)
        rt_total = sum(pres2.Slides(i).TimeLine.MainSequence.Count for i in range(1, pres2.Slides.Count + 1))
        pres2.Close()
        os.remove(rt)
        print(f"  往返保存后动画总数：{rt_total}（{'一致 ✅' if rt_total == total else '不一致 ❌'}）")
        ok = ok and rt_total == total
    finally:
        try:
            pres.Close()
        except Exception:
            pass
    return ok


def main() -> None:
    app = win32.DispatchEx("PowerPoint.Application")
    results = {}
    try:
        for label, path in FILES:
            if not os.path.exists(path):
                print("missing:", path)
                continue
            results[label] = check(app, label, path)
    finally:
        try:
            app.Quit()
        except Exception:
            pass
    print("\n结论：", "全部通过 ✅" if results and all(results.values()) else f"有问题 ❌ {results}")
    sys.exit(0 if results and all(results.values()) else 1)


if __name__ == "__main__":
    main()
