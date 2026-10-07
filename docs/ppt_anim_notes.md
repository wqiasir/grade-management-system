# PPT 出场动画实现与踩坑记录

> 这份文档记录"怎么往 pptx 里写出场动画"以及**两个会导致 PowerPoint 打不开/动画丢失的坑**，
> 可以作为课程报告"开发日志 / 技术实现"章节的素材。结论全部在本机 PowerPoint 上用 COM 实测得出。

---

## 一、为什么不能直接用 python-pptx 加动画

`python-pptx` 1.0.2 **没有动画 API**（`Shape` 上没有 animation 相关接口）。
但动画本身只是幻灯片 XML 里的一段 `<p:timing>` 树，所以做法是：

1. 用 python-pptx 正常生成页面与形状（拿到稳定的 `shape_id`）；
2. 自己构造 `<p:timing>` 子树，塞进 `slide._element`；
3. 保存后用 PowerPoint 打开，读 `Slides(i).TimeLine.MainSequence` 验证效果数量与触发方式。

关键点：**形状的 `shape_id` 必须与 timing 里 `<p:spTgt spid="...">` 一一对应**，
所以我们给每个动画都登记 `shape.shape_id`，而不是事后猜。

---

## 二、正确的 timing 结构（照抄 PowerPoint 自己的输出）

先用 COM 让 PowerPoint 自己给 3 个形状加淡入动画并另存，再解压 `ppt/slides/slideN.xml`，
得到权威结构（`probe_powerpoint_native.py` 就是这个用途）：

```
<p:timing>
  <p:tnLst>
    <p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot">
      <p:childTnLst>
        <p:seq concurrent="1" nextAc="seek">                    ← 绝不能有 prevAc！
          <p:cTn id="2" dur="indefinite" nodeType="mainSeq">
            <p:childTnLst>
              <p:par><p:cTn id="3" fill="hold">                 ← 第 1 层：外层分组
                  <p:stCondLst><p:cond delay="indefinite"/></p:stCondLst>
                  <p:childTnLst>
                    <p:par><p:cTn id="4" fill="hold">           ← 第 2 层：把 set+效果绑成一个单元
                        <p:stCondLst><p:cond delay="0"/></p:stCondLst>
                        <p:childTnLst>
                          <p:par><p:cTn id="5" presetID="10" presetClass="entr"
                                        presetSubtype="0" fill="hold" grpId="0"
                                        nodeType="clickEffect">   ← 第 3 层：效果本体
                              <p:childTnLst>
                                <p:set>... style.visibility → visible ...</p:set>
                                <p:animEffect transition="in" filter="fade">
                                  <p:cBhvr><p:cTn id="6" dur="500"/>
                                           <p:tgtEl><p:spTgt spid="2"/></p:tgtEl>
                                  </p:cBhvr>
                                </p:animEffect>
                              </p:childTnLst>
                          </p:cTn></p:par>
                        </p:childTnLst>
                    </p:cTn></p:par>
                  </p:childTnLst>
              </p:cTn></p:par>
            </p:childTnLst>
          </p:cTn>
          <p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>
          <p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst>
        </p:seq>
      </p:childTnLst>
    </p:cTn></p:par>
  </p:tnLst>
  <p:bldLst><p:bldP spid="2" grpId="0"/>…</p:bldLst>
</p:timing>
```

三种出场效果对应的属性：

| 效果 | presetID | presetSubtype | filter |
| --- | --- | --- | --- |
| 淡入 | 10 | 0 | `fade` |
| 左擦除 | 22 | 4 | `wipe(left)` |
| 浮入（自下浮起+淡入） | 42 | 8 | `fade`，另加 `<p:anim>` 改 `ppt_y` |

---

## 三、两个坑（都实测复现过）

### 坑 1：`<p:seq prevAc="...">` 会让 PowerPoint **打不开文件**

- 现象：COM `Presentations.Open` 报 `0x80070010`（ERROR_BAD_ENVIRONMENT），
  PowerPoint 界面里则是"内容有问题，需要修复"。
- 单变量对照（`probe_prevac.py`）：

  | 写法 | 结果 |
  | --- | --- |
  | 省略 `prevAc` | ✅ 能打开 |
  | `prevAc="enabled"` | ❌ 打不开 |
  | `prevAc="seek"` | ❌ 打不开 |

  也就是说**只要这个属性出现就拒绝加载**，与取值无关。
- 结论：PowerPoint 自己的输出从不写 `prevAc`（它用 `prevCondLst/nextCondLst` 表达同一语义）。
  **不要写这个属性。**

### 坑 2：只写两层 `<p:par>` 会让每个动画"裂成两个"

- 现象：文件能打开，但 `MainSequence.Count` 是元素数量的 2 倍（486 个元素读成 1028），
  而且**偶数项读 `.Timing.TriggerType` 直接报 `Timing.TriggerType : Failed`**。
- 原因：少写第 2 层 par 时，`<p:set>`（设置可见性）与 `<p:animEffect>`（淡入）
  被 PowerPoint 当成两个独立动画。
- 结论：**必须三层 par 嵌套**（外层分组 / 绑定单元 / 效果本体）。

### 附带结论

- `nodeType` 只能取 `tmRoot / mainSeq / clickEffect / withEffect / afterEffect`，
  不能把预设名（`fade`、`wipe`）写进去。
- `<p:timing>` 在 `<p:sld>` 里的位置要正确：`cSld → clrMapOvr → transition → timing`。
- `<p:bldLst>` 要列出所有参与动画的形状，PowerPoint 才按"对象"构建。

---

## 四、本项目的动画节奏设计

一页里几十个形状如果每个都要点一下，讲起来会很累。所以引入**"单击点（beat）"**：

- 同一个 beat 里的元素**一次点击一起出现**（第一个是 `clickEffect`，其余是 `withEffect`）；
- 每个 beat 是一个语义单元，例如"一张卡片 + 卡片的标题 + 正文"。

按页统计（单击版）：共 **486 个出场效果**，分在 **278 次单击**里
（其余 208 个是 `withEffect`，与所在 beat 同时出现）。平均每页约 15 次点击。

自动播放版（`PPT_ANIM_MODE=auto`）把这些全部改成"上一动画之后"，
按 `EFFECT_DUR(500ms) + AUTO_DELAY(350ms)` 递增延时，**零点击自动放完**，并加了 0.5 秒淡入换片。

---

## 五、验证方法（可复现）

```powershell
cd D:\作业\软件工程课程实践\project
$env:PYTHONIOENCODING='utf-8'

# 1) 静态结构校验：包完整性、动画 spid 是否对得上形状、nodeType 合法性、cTn id 唯一
python docs\ppt_assets\verify_ppt.py

# 2) 用 PowerPoint 真机验证：能否打开 + 逐页读回效果数量/类型/触发方式 + 往返保存后再读
python docs\ppt_assets\verify_with_powerpoint.py

# 3) 单独复现两个坑
python docs\ppt_assets\probe_prevac.py            # prevAc 对照实验
python docs\ppt_assets\probe_beat.py              # beat 写法的 TriggerType 对照
python docs\ppt_assets\probe_powerpoint_native.py # 生成 PowerPoint 原生动画作为参考
```

`verify_with_powerpoint.py` 在交付物上的实测输出：

```
单击版：19 页打开成功；slide01: 13 个动画 Rectangle 1/10/单击/0.5s …
        合计 486 个动画；往返保存后动画总数：486（一致）
自动播放版：合计 486 个动画，触发方式全部为"上一动画之后"
```

> 注意：`Timing.TriggerType` 在本机读回时，本工具对"单击"的映射与 PowerPoint UI 的
> 中文表述偶有出入，判断动画是否成功**以"数量是否为元素个数、往返保存后是否守恒"为准**。
