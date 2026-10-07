# -*- coding: utf-8 -*-
"""对照实验：同一"单击点"的多个元素，用哪种写法 PowerPoint 才当作一次点击？

三种写法：
  A. 每个元素一个外层组，delay=indefinite（当前做法）→ 预期每次都要点
  B. 第一个元素 clickEffect(indefinite)，其余 withEffect(delay=0)
  C. 同一单击点的元素**共用同一个条件节点**（多个外层组引用同一个 stCondLst id）

结论看 PowerPoint 读回的 TriggerType 序列。
"""

from __future__ import annotations

import os

from lxml import etree
from pptx import Presentation
from pptx.util import Inches
import win32com.client as win32

P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_probe")
os.makedirs(OUT, exist_ok=True)
DUR = 500

CASE_INFO = {
    "A": "每个元素独立外层组 + delay=indefinite",
    "B": "首个 clickEffect + 其余 withEffect(delay=0)",
    "C": "同一点击点共用同一个 cond id",
}


def base(path: str, n: int = 4) -> None:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    for i in range(n):
        b = slide.shapes.add_textbox(Inches(1), Inches(0.8 + i * 1.4), Inches(8), Inches(1))
        b.text_frame.text = f"形状{i + 1}"
    prs.save(path)


def sub(parent, tag, **attrs):
    el = etree.SubElement(parent, P + tag)
    for k, v in attrs.items():
        el.set(k, str(v))
    return el


def effect_node(tn_lst, sid, nid, node_type):
    par = sub(tn_lst, "par")
    e = sub(par, "cTn", id=nid, presetID=10, presetClass="entr", presetSubtype=0,
            fill="hold", grpId="0", nodeType=node_type)
    nid += 1
    st = sub(e, "stCondLst")
    sub(st, "cond", delay=0)
    inner = sub(e, "childTnLst")
    s = sub(inner, "set")
    cb = sub(s, "cBhvr")
    ctn = sub(cb, "cTn", id=nid, dur=1, fill="hold"); nid += 1
    sc = sub(ctn, "stCondLst"); sub(sc, "cond", delay=0)
    t = sub(cb, "tgtEl"); sub(t, "spTgt", spid=sid)
    an = sub(cb, "attrNameLst"); sub(an, "attrName").text = "style.visibility"
    to = sub(s, "to"); sub(to, "strVal", val="visible")
    ae = sub(inner, "animEffect", transition="in", filter="fade")
    acb = sub(ae, "cBhvr")
    sub(acb, "cTn", id=nid, dur=DUR); nid += 1
    at = sub(acb, "tgtEl"); sub(at, "spTgt", spid=sid)
    return nid


def inject(path: str, case: str, groups: list[list[int]]) -> None:
    prs = Presentation(path)
    slide = prs.slides[0]
    ids = [sh.shape_id for sh in slide.shapes]
    root = slide._element
    timing = etree.SubElement(root, P + "timing")
    tn = sub(timing, "tnLst")
    rp = sub(tn, "par")
    rctn = sub(rp, "cTn", id=1, dur="indefinite", restart="never", nodeType="tmRoot")
    c1 = sub(rctn, "childTnLst")
    seq = sub(c1, "seq", concurrent=1, nextAc="seek")
    main = sub(seq, "cTn", id=2, dur="indefinite", nodeType="mainSeq")
    mc = sub(main, "childTnLst")
    nid = 3
    shared_cond_id = None
    for gi, group in enumerate(groups):
        # 外层组
        outer = sub(mc, "par")
        octn = sub(outer, "cTn", id=nid, fill="hold"); nid += 1
        ost = sub(octn, "stCondLst")
        oc = sub(ost, "cond")
        if case == "A" or (case == "C" and gi == 0):
            oc.set("delay", "indefinite")
        elif case == "B":
            oc.set("delay", "indefinite" if gi == 0 else "0")
            if gi:  # B：后续组是接续，不是新一轮点击
                pass
        if case == "C":
            if gi == 0:
                oc.set("delay", "indefinite")
                shared_cond_id = str(nid)
                oc.set("id", shared_cond_id); nid += 1
            else:
                oc.set("id", shared_cond_id)
                oc.set("delay", "indefinite")
        och = sub(octn, "childTnLst")
        for k, sid in enumerate(group):
            mp = sub(och, "par")
            mctn = sub(mp, "cTn", id=nid, fill="hold"); nid += 1
            ms = sub(mctn, "stCondLst"); sub(ms, "cond", delay=0)
            mch = sub(mctn, "childTnLst")
            if case == "B":
                nt = "clickEffect" if (gi == 0 and k == 0) else "withEffect"
            else:
                nt = "clickEffect"
            nid = effect_node(mch, ids[sid - 1], nid, nt)
    # seq 的前进/后退条件（PowerPoint 自己会写，缺了动画会被丢弃）
    prev = sub(seq, "prevCondLst")
    pc = sub(prev, "cond", evt="onPrev", delay=0)
    pte = sub(pc, "tgtEl"); sub(pte, "sldTgt")
    nxt = sub(seq, "nextCondLst")
    nc = sub(nxt, "cond", evt="onNext", delay=0)
    nte = sub(nc, "tgtEl"); sub(nte, "sldTgt")
    bld = sub(timing, "bldLst")
    for sh in slide.shapes:
        sub(bld, "bldP", spid=sh.shape_id, grpId="0")
    prs.save(path)


def read(path: str) -> str:
    app = win32.DispatchEx("PowerPoint.Application")
    try:
        pres = app.Presentations.Open(os.path.abspath(path), ReadOnly=True,
                                      Untitled=False, WithWindow=False)
        seq = pres.Slides(1).TimeLine.MainSequence
        out = [f"count={seq.Count}"]
        for j in range(1, seq.Count + 1):
            e = seq.Item(j)
            try:
                out.append(f"{e.Shape.Name}:{e.EffectType}/T{e.Timing.TriggerType}")
            except Exception as exc:
                out.append(f"{e.Shape.Name}:ERR({exc})")
        pres.Close()
        return " | ".join(out)
    except Exception as exc:
        return f"打开失败 {exc}"
    finally:
        try:
            app.Quit()
        except Exception:
            pass


def main() -> None:
    # 两个单击点，各含 2 个元素
    groups = [[1, 2], [3, 4]]
    for case in ("A", "B", "C"):
        p = os.path.join(OUT, f"beat_{case}.pptx")
        if os.path.exists(p):
            os.remove(p)
        base(p)
        inject(p, case, groups)
        print(f"\n【{case}】{CASE_INFO[case]}")
        print("   ", read(p))


if __name__ == "__main__":
    main()
