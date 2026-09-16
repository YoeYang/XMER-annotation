# 人脸轨迹（V3 轨道 A1）

把 `visual.mp4` 里说话人的脸**逐帧**跟出来，供下一步切 `face.mp4`（裁出脸）
与 `body.mp4`（遮住脸）。V3 把原来的 `visual` 模态拆成 face / body 两个子任务，
就靠这条轨迹。

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

## 流程

| 步 | 做什么 |
| --- | --- |
| 1 | 读 `frames/<样本>.jpg` 算 SFace 身份模板 |
| 2 | `visual.mp4` 逐帧 YuNet 检测 |
| 3 | 过滤背景路人（`det<0.70`、脸高 `<7%` 画面高） |
| 4 | 按 `sim + 0.30 × IoU(上一帧)` 选人——相似度定身份，IoU 定连贯 |
| 5 | 空洞线性插值，标 `src="interp"` |
| 6 | 中值窗 + EMA 平滑 |
| 7 | 判级 ok / low_confidence / drop |

> **第 6 步不是可选项。** 裁剪框逐帧跟着检测噪声跳，标注者看到的画面会持续抖，
> 注意力被抖动本身带跑，直接污染 arousal。

## 判级

命中一条标 `low_confidence`，两条以上标 `drop`。**只打标不自动删**，去留由 A3 人工审核定。

| 判据 | 阈值 |
| --- | --- |
| 检出率 | `< 0.60` |
| 最大连续空洞 | `> 0.5s` |
| 平均相似度 | `< 0.363`（SFace 官方同人阈值） |
| 平均脸高占比 | `< 0.07` |

单帧接受门限 `SIM_ACCEPT = 0.25` 刻意**低于** 0.363：侧脸、运动模糊、低光会让
单帧相似度掉下去，按 0.363 卡会打出一堆假空洞。身份可信与否改由**轨迹均值**把关。

## 怎么跑

```bash
sbatch --array=0-31 track.sbatch                              # 全量 3440 条
sbatch --array=0-0 track.sbatch --samples out/pilot50.txt     # 试点
```

x86 `small` 分区，**纯 CPU**——YuNet 与 SFace 都是 OpenCV 的 ONNX CPU 实现，
GPU 一点用不上（实测 x86 比 GH200 还快 25%）。环境见记忆
`xmer-roihu-env-slurm`：系统 `/usr/bin/python3` + `PYTHONUSERBASE` 指向
`conflict-sampling-x86`，**不要 `module load`**（模块都是 ARM 容器）。

断点续跑：输出文件已存在就跳过，重跑不会重算；落盘走 `os.replace` 原子替换，
中断不会留下半个文件。

## 产物

`out/tracks/<样本>.json`，一样本一文件：

```json
{"sample_id":"...", "fps":25.0, "n_frames":109, "w":1920, "h":724,
 "track":[{"i":0,"bbox":[x,y,w,h],"det":0.98,"sim":0.71,"src":"det|interp"}, ...],
 "stats":{"detected":105,"interpolated":4,"missing":0,
          "max_gap_frames":2,"max_gap_seconds":0.08,
          "det_rate":0.963,"mean_sim":0.68,"mean_face_h_ratio":0.29},
 "status":"ok|low_confidence|drop", "reasons":[]}
```

`src` 字段是溯源信息：`interp` 的帧是插值猜的，A3 人工审核时一眼能看出来。
平滑只动 `bbox`，不动 `det`/`sim`/`src`。

## 测试

```bash
export PYTHONUSERBASE=/projappl/project_2017416/python-package/conflict-sampling-x86
/usr/bin/python3 -m pytest tests -q          # 24 个，全部是构造数据，不碰视频
```

`trackcore.py` 刻意不 import cv2 也不碰文件系统，全部是可单测的纯计算；
检测与读写在 `track.py`，两者的接缝是「每帧候选脸列表」这一种数据结构。

> 测试里的相似度一律取 0.20 / 0.50 这种**远离** `SIM_ACCEPT=0.25` 的值。
> handover 记过一次教训：边界值测试要避开被测逻辑的分界点，
> 否则断言会因浮点误差无谓地红。
