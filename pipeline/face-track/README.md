# 人脸轨迹与 face / body 素材（V3 轨道 A）

V3 把原来的 `visual` 模态拆成 **face**（只看脸）与 **body**（脸被遮住、只看身体）
两个子任务，这里负责把它们做出来。

## 核心：只借 manifest 的「身份」，不借它的「坐标」

`06-speaker-frames/out/manifest.jsonl` 里的 `bbox` 与 `source_time` 是在
**原始数据集视频**的坐标系上算的；而 `visual.mp4` 已经过 chsims 裁字幕、
iemocap 裁黑边、`recrop_visual.py` 重裁——**两者坐标系对不上，直接拿来用会错位**。

所以改成：

```
身份模板 ← frames/<样本>.jpg（已人工核对过的说话人脸）→ SFace 128 维特征
轨迹     ← visual.mp4 逐帧 YuNet 检测，每个候选脸与模板算余弦相似度
```

完全绕开坐标系问题，同时白拿了那 3440 条已人工核对的说话人身份。

## 两个模态用两套框，刻意不共用

| | face | body |
| --- | --- | --- |
| 用哪个框 | `cx/cy + side` 的**稳定大框**（固定尺寸、慢速平移） | 每帧**实际检测框** |
| 为什么 | 要**稳**——框抖会让标注者的注意力被抖动带跑，污染 arousal | 要**准**——拿稳定框去遮，镜头一切就盖到旁边人脸上了 |
| 迟滞 | **有**，防屏闪 | **无** |
| 认不出的帧 | **黑屏** | **不遮** |
| 框大小 | 人脸 × 1.4（`CROP_MARGIN=0.20`） | 人脸 × 1.2（`BODY_MASK_EXPAND=0.10`） |
| 输出 | 320×320 正方形 | 原画面尺寸不变 |

**body 只蒙说话人一个人。** 画面里别人的脸不能蒙——那块黑色本身就是在指认
「该看谁的身体」，全蒙了标注者就不知道该读谁了。

**body 的遮挡块宁小勿大。** 判据是「看不见五官」，不是「看不见整个头」：
盖到脖子肩膀就把身体语言一起吃掉了，而头部动作本身也是动作，露一点头顶没关系。

## 不追求逐帧跟准

侧脸、低头、运动模糊检不出人脸是**常态，不是样本有问题**。早期版本用
「最大连续空洞 > 0.5s」判刑，把 meld 误杀 22%、mustard 误杀 52%——这条判据已废除。

现在的做法：

- **face 的框固定尺寸、慢速平移**，检不出的帧框留在原处，画面照常播真实帧
  （而不是冻结画面糊弄标注者）；固定尺寸同时消掉缩放抖动
- **可见性做时域迟滞**（`smooth_presence`）：短于 `HOLD_SECONDS=0.40` 的丢失
  当人还在，继续显示；短于 `MIN_VISIBLE_SECONDS=0.20` 的可见段抹掉。
  不做迟滞的话画面会在「真实帧 / 黑屏」之间高频交替，**看着像屏闪、眼睛很痛**
  —— 试点实测最坏从 14 次黑白切换降到 3 次
- 位移小于框边长 10% 时退化成**全段静态框**

## 判级

只有两条，命中即 `drop`；`ok` 与 `low_confidence` 之间按可见率分。

| 判据 | 阈值 | 说明 |
| --- | --- | --- |
| 可见率 | `< 0.30` | 等价于「黑屏 > 70%」，Yoe 定的口径 |
| 平均相似度 | `< 0.363` | SFace 官方同人阈值，低于它是**认错人**而非「检不出」 |

`low_confidence`：可见率落在 `[0.30, 0.50)`，能标，但值得人工先看一眼。
**只打标不自动删**，去留由 A3 的人工审核定。

单帧接受门限 `SIM_ACCEPT = 0.25` 刻意**低于** 0.363：侧脸、运动模糊、低光会让
单帧相似度掉下去，按 0.363 卡会打出一堆假空洞。身份可信与否由**轨迹均值**把关。

## CROP_MARGIN 是扫出来的，不是拍脑袋

在试点 50 条上扫过：

```
margin   脸完整在框内   脸占框面积   覆盖<95%的样本
 0.60       99.4%        13.7%          1     <- speaker-frames 静帧的原值
 0.25       98.9%        29.1%          4
 0.20       98.7%        33.4%          5     <- 取用
 0.15       97.9%        38.7%         11     <- 拐点，明显劣化
```

静帧那个 0.6 是给人核对身份用的，留白无所谓；这里是给标注者看表情的，
脸要尽量占满画面。0.20 让脸占的面积变成原来的 2.4 倍，覆盖率只掉 0.7 个百分点。

## 怎么跑

```bash
# 1. 轨迹（全量 3440 条，x86 small 分区，约 2.5 分钟）
sbatch --array=0-31 track.sbatch
sbatch --array=0-0 --partition=test track.sbatch --samples out/pilot50.txt   # 试点

# 2. 素材
/usr/bin/python3 src/render.py --samples out/vid_examples.txt --kind both

# 3. 人工核对用的对照图
/usr/bin/python3 src/preview.py --samples out/sheet_all.txt --out out/preview
```

**纯 CPU**——YuNet 与 SFace 都是 OpenCV 的 ONNX CPU 实现，GPU 一点用不上
（实测 x86 53.4 帧/秒/核，比 GH200 的 42.7 还快 25%）。环境见记忆
`xmer-roihu-env-slurm`：系统 `/usr/bin/python3` + `PYTHONUSERBASE` 指向
`conflict-sampling-x86`，**不要 `module load`**（模块都是 ARM 容器）。

断点续跑：输出已存在即跳过；落盘走 `os.replace` 原子替换，中断不留半个文件。

## 产物

`out/tracks/<样本>.json`，一样本一文件：

```json
{"sample_id":"...", "fps":25.0, "n_frames":109, "w":1920, "h":724,
 "crop":{"mode":"static|slow", "side":277.2,
         "frames":[{"i":0,"cx":321.4,"cy":156.1,
                    "present":1,"visible":1,"bbox":[x,y,w,h]}, ...]},
 "stats":{"detected":105,"face_present_ratio":0.963,"face_inside_ratio":0.99,
          "visible_ratio":0.99,"black_ratio":0.01,"flicker_cuts":1,
          "max_gap_frames":2,"max_gap_seconds":0.08,
          "det_rate":0.963,"mean_sim":0.68,"mean_face_h_ratio":0.29},
 "status":"ok|low_confidence|drop", "reasons":[]}
```

- `present` 是**原始检出**，`visible` 是**迟滞后**的可见标记（face 用后者）
- `bbox` 是该帧**实际检到**的框，只在 `present` 时有值（body 用它）
- 早期失败（视频缺失、静帧检不出脸）也写出完整形状的 `stats`，
  下游读字段不会 KeyError

## 时长必须与源一致

前端加载时核对媒体实际时长与任务清单，**差超过 0.25 秒就拒绝打开该任务**；
同一样本五个模态还共用一条时间轴，长度不一致的话曲线合并时对不齐。
所以 `render.py` 不重采样、不丢帧、不补帧，源有多少帧写多少帧，**写完逐条核对**。

> 数帧**不要用 `ffmpeg -c copy -f null -`** —— 流拷贝不解码，不打印 `frame=` 计数，
> 拿到的永远是 -1（第一版就栽在这，把 15 条全渲染成功的报成了失败）。
> 容器元数据也会虚报（iemocap 声称 266 帧实际只有 52 帧），所以老老实实解一遍。

x86 上没有能编码 H.264 的 ffmpeg 模块（spack 那个不带 libx264，cv2 的 VideoWriter
只有 mp4v 能开），用的是装在 `conflict-sampling-x86` 里的静态构建。

## 测试

```bash
export PYTHONUSERBASE=/projappl/project_2017416/python-package/conflict-sampling-x86
/usr/bin/python3 -m pytest tests -q          # 40 个，全部构造数据，不碰视频
```

`trackcore.py` 刻意不 import cv2 也不碰文件系统，全部是可单测的纯计算；
检测与读写在 `track.py`，两者的接缝是「每帧候选脸列表」这一种数据结构。

> 测试里的相似度一律取 0.20 / 0.50 这种**远离** `SIM_ACCEPT=0.25` 的值，
> 可见率也避开 0.30 / 0.50 两个门槛本身。handover 记过一次教训：
> 边界值测试要避开被测逻辑的分界点，否则断言会因浮点误差无谓地红。
