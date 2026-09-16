# 新 session 起手 prompt：说话人静帧预处理

> 把下面 `---` 之间的整段贴给新 session 即可。

---

Yoe，先读 `/scratch/project_2017416/yyy2026/.claude/CLAUDE.md`（工作规则：全程中文、称呼我 Yoe、写代码前先给方案等我批准）。
本任务在 `/scratch/project_2017416/yyy2026/XMER/06-speaker-frames/` 下开展，是一个**独立的数据预处理程序**，不改动 `05-annotation/` 的任何代码。

## 背景

XMER 项目在做连续情感标注（Valence-Arousal）。标注者要对同一样本分别标"仅视觉/仅音频/仅文本"三个单模态，
再标完整视频。为避免跨模态污染，完整视频被排到最后——但多人场景里标注者就不知道该标谁了。

解决办法：**每个样本预先提取一张"目标说话人"的静态帧**，标注时常驻页面提示"按这个人标注"。
这张图是**任务说明，不是被评定的材料**，用途只有身份识别。

你要做的就是批量产出这 3500 张图。

## 输入

样本池：`/scratch/project_2017416/yyy2026/XMER/04-conflict-sampling/0-conflict_sample_selection/data/annotation_pool_3500.jsonl`
每行有 `sample_id` 和 `source`。3500 条唯一样本，来源分布：

| source | 条数 | sample_id 形如 |
| --- | --- | --- |
| meld | 920 | `meld_dia556_utt6` |
| chsims | 919 | `chsims_aqgy5_0024_00014` |
| iemocap | 877 | `iemocap_Ses05F_impro03_F042` |
| mosi | 521 | `mosi_c5xsKMxpXnc_7` |
| mustard | 263 | `mustard_1_2616` |

素材根目录 `/scratch/project_2017416/yyy2026/datasets/`：

- `MELD/train_sent_emo.csv` —— **含 `Speaker` 列**（Friends 角色名），视频在 `/scratch/project_2007389/yyy/MELD.Raw/train_splits/dia{N}_utt{M}.mp4`
- `MUStARD/sarcasm_data.json` —— key 形如 `1_2616`，**含 `speaker`（如 SHELDON）和 `show`（如 BBT）**；视频 `MUStARD/new_data/{SCENE}/video.mp4`
- `CMU-MOSI/mosi_interface.csv` —— `id,video_path,transcription,dataset`
- `iemocap-clip/iemocap_interface.csv` —— 同上；另有 `clips/` 与 `iemocap-full-videos/`
- `CH-SIMS/ch-simsv2s/ch-sims-interface.csv` 与 `meta.csv`

**第一步请先核实每个来源的 sample_id 到视频文件的映射规则**，五个数据集命名各不相同，别想当然。

## 关键：难度按数据集差一个数量级，不要统一处理

这是整个任务最重要的设计判断。**不要把 3500 段视频都送进 Gemini**，那既慢又贵，而且大部分是浪费：

| 来源 | 条数 | 难度 | 建议做法 |
| --- | --- | --- | --- |
| **mosi** | 521 | 极易 | YouTube 独白 vlog，画面基本只有一个人。跑本地人脸检测取最大/最居中的脸即可，**无需任何 API** |
| **iemocap** | 877 | 易 | 两人对话固定机位；`sample_id` 里的 `F042`/`M009` **已编码说话人性别**。候选只有两张脸，性别已知即可判别。同一 session 的左右位置固定，**每个 session 判一次即可复用**，877 条可能只需几十次判断 |
| **meld** | 920 | 中 | **说话人姓名已知**（Friends 角色）。Gemini 认识这些角色，给几帧 + 角色名让它框出人脸即可，**不需要唇动信息，静帧就够** |
| **mustard** | 263 | 中 | 同上，`speaker` + `show` 已知（BBT/Friends 等） |
| **chsims** | 919 | 难 | 中文影视，**无说话人元数据**，多人同框。这是唯一真正需要判断"谁在说话"的部分 |

所以真正的硬骨头只有 **chsims 的 919 条**。请优先把前四类用便宜手段吃掉，再集中火力处理 chsims。

### chsims 的两条路线，请评估后给我建议

- **路线 A（Gemini 传视频）**：flash 支持视频输入，直接问"谁在说话、框出他的人脸"。实现简单，但 919 段视频上传有成本和速率限制。
- **路线 B（本地 ASD 模型）**：TalkNet-ASD / Light-ASD 这类主动说话人检测模型就是为这个任务做的，输出逐帧的说话人框。**Roihu 有 GPU**，跑完零 API 成本，准确率通常高于让通用多模态模型猜。代价是要装模型和依赖。

我倾向先做小规模对照再定。**不要直接开跑 919 条**。

## 输出契约（必须严格遵守，下游 05-annotation 直接消费）

```
06-speaker-frames/
  out/
    frames/<sample_id>.jpg          # 裁切好的说话人面部
    manifest.jsonl                  # 每行一条
    review/                         # 人工核对用的联系表网格页
```

`manifest.jsonl` 每行：

```json
{
  "sample_id": "meld_dia556_utt6",
  "source": "meld",
  "speaker_name": "Phoebe",          // 无元数据时为 null
  "frame_path": "frames/meld_dia556_utt6.jpg",
  "source_time": 1.84,               // 该帧在原视频中的时刻（秒）
  "bbox": [x, y, w, h],              // 原视频坐标系下的人脸框
  "method": "gemini|asd|largest-face|gender-rule",
  "confidence": 0.0,
  "status": "ok|needs_review|failed",
  "note": ""
}
```

选帧标准：**正脸清晰、未被遮挡，怎么好认怎么来**。不要为了别的目标牺牲辨识度。

## 人工核对工具（必做，不是可选）

模型定位快，但**说话主体是否正确必须由人确认**——静帧指错了人，该样本四个模态的标注会一起作废。

3500 张逐条审查不现实，请做成**联系表式网格页**：一屏铺上百张裁切图并标注 `sample_id` 和人名，
研究者只需扫视并点出错的那些，把逐条审查压缩成扫视。输出可以是静态 HTML，点击标记后导出一个
`rejected.txt`（每行一个 sample_id）即可，不需要后端。

## 工程要求

1. **可断点续跑**。3500 次处理必然中途失败，进度写 `manifest.jsonl`，重跑自动跳过已完成的。
2. **先跑小样本再放量**。每个来源先跑 30–50 条，我人工看准确率和成本，确认后再全量。**这一步不要跳过**。
3. **失败单独归桶**，`status: failed` 的留到最后人工处理，不要让个别失败卡住整批。
4. **并发与限速**可配置；如走 Gemini，先给我一个**成本估算**再开跑。
5. Gemini 的 bbox 返回的是归一化到 0–1000 的 `[ymin, xmin, ymax, xmax]`，注意换算，别搞反坐标顺序。
6. 在 Roihu 上跑：`module load ffmpeg/7.1`，Python 用 `module load python-data/3.12-20.04`（注意 `module load` 那行**不能接管道**，管道会开子 shell 导致 PATH 改动丢失）。

## 请你先做的事

**不要立即写代码**（CLAUDE.md 规则 4）。请先：

1. 核实五个来源的 `sample_id` → 视频文件映射，报告有多少条能对上、多少条缺素材
2. 抽查几段视频，确认画面里到底有几个人（尤其 mosi 是不是真的单人、iemocap 是不是固定双人同框）
3. 给我一个方案：每个来源用什么手段、chsims 走 A 还是 B、预计耗时与成本
4. 等我批准后再动手，先跑小样本

---

## 给 05-annotation 这边的说明（不用贴给新 session）

- 产出的 `frames/<sample_id>.jpg` 与 `manifest.jsonl` 将在**素材导入**阶段被读入 `tasks` 表的
  `speaker_ref_src` 与 `speaker_name` 两个字段（`server/app/models.py` 已预留）。
- **T4 开发只需要 1 张**（示例样本 `meld_dia11_utt9`），可以先手工截一张应急，不必等全量。
- 全量 3500 张是**素材导入与 P1 pilot 的前置工序**，`manage.py apply-plan` 要求 tasks 表里有真实样本。
