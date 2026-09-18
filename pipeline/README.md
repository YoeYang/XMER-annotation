# 素材准备流水线

把 `04-conflict-sampling` 选出来的样本，加工成标注平台能播的四模态素材。

原先这三步分散在 `06-speaker-frames`、`07-text-alignment`、`08-material-prep`
三个目录里，靠 9 处写死的绝对路径互相 `sys.path.insert`——其中
`build_tasks.py` 还直接 import 了标注平台的 `server/app/assignments`。
它们本来就是一套代码，2026-09-16 合并到这里。

## 三步做什么

```
speaker-frames ─┐
text-alignment ─┼→ material-prep → out/media/<样本>/{visual.mp4, audio.m4a,
                ┘                                    audiovisual.mp4, speaker.jpg}
                                   out/transcripts/<样本>.json
                                   out/tasks_import.json
```

| 目录 | 做什么 | 主要产物 |
| --- | --- | --- |
| `speaker-frames/` | 找出视频里真正在说话的人，截一张静帧。扫脸 → 唇动 → Gemini 判定 → 人工核对页 → 落地 | `frames/`（3440 张）、`manifest.jsonl`、`discarded.txt` |
| `text-alignment/` | wav2vec2 CTC 强制对齐，算出每个词的起止时间。中英双语，带**永不丢词**的硬断言 | `align/shard-*.jsonl`（3440 条词级时间戳） |
| `material-prep/` | 切出四模态素材、裁掉 chsims 硬字幕与 iemocap 黑边、生成转录稿与任务清单 | `media/`（3440 个样本目录）、`transcripts/`、`tasks_import.json` |

`speaker-frames/src/common.py` 与 `facelib.py` 等是三步共用的，另外两步直接从这里导入，
没有单独抽 `common/`——17 个脚本依赖它，抽出来要改一大片 import，不值得。

## 代码在仓库里，数据不在

`out/`、`models/`、`data/` 加起来十几 GB，仍留在 Roihu 的 scratch 上，
**只有代码进 git**。两者由 `datapaths.py` 接起来：

```python
DATA_ROOT = Path(os.environ.get("XMER_DATA_ROOT", "/scratch/project_2017416/yyy2026/XMER"))
```

换机器或换存储位置时设 `XMER_DATA_ROOT` 就行，脚本一行不用改。
所有数据路径都从这里取，不要在脚本里再写绝对路径。

## 怎么跑

Roihu 上两套环境，按需要的库选：

```bash
module load python-data/3.12-20.04      # 不需要 torch 的步骤，自带 ffmpeg 8.0.1
module load python-pytorch/2.13         # 对齐需要 torch / torchaudio / transformers
```

> **ffmpeg 有两个，只有一个能编码。** spack 的 `ffmpeg/7.1` **不带 libx264**，
> `-crf` 会报 `Unrecognized option 'crf'`；`python-data` 自带的 8.0.1 才能编。
> 后加载的模块覆盖 PATH，**加载顺序决定用哪个**。

```bash
cd pipeline/speaker-frames && ./run.sh <步骤>          # 静帧，见 README.md
cd pipeline/text-alignment && sbatch align.sbatch      # 对齐，GH200 分区
cd pipeline/material-prep  && sbatch prepare.sbatch    # 素材，8 个分片
python material-prep/src/recrop_visual.py              # 重裁（登录节点并行即可）
```

Slurm 作业脚本用 `cd "$SLURM_SUBMIT_DIR"` 加相对路径，从哪提交都能跑。

> **计算分区是 x86，登录节点与 GPU 分区是 ARM。** pytorch、ffmpeg 这些模块是 ARM 容器，
> 投到 `small`/`test` 等 x86 分区会报架构不符。要这些模块的作业投 `gpumedium`
> （GH200，须带 `--gres=gpu:gh200:1`）；纯 ffmpeg 的活可以在登录节点多进程并行。

## 改了素材之后

`recrop_visual.py` 这类改动会让视频时长变化。前端在加载时核对媒体实际时长与任务清单，
**差超过 0.25 秒就拒绝打开该任务**。所以重新处理素材后必须跟着跑一次：

```bash
python manage.py set-durations --file <{task_id: 秒数}.json>
```

## 测试

```bash
cd material-prep && python -m pytest tests -q     # 7 个，转录稿格式与边界
cd text-alignment && python -m pytest tests -q    # 10 个，对齐保真度（需 pytorch 模块）
```

`speaker-frames` 的 21 个脚本没有自动化测试，改动后只能人工核对产物。

## 在 Roihu 上跑前端测试

Roihu 没装 node，但有 singularity，一次性容器就能跑：

```bash
singularity pull node20.sif docker://node:20-alpine
singularity exec -B "$PWD:/src" --pwd /src node20.sif npm ci
singularity exec -B "$PWD:/src" --pwd /src node20.sif npm test -- --run
singularity exec -B "$PWD:/src" --pwd /src node20.sif npx tsc --noEmit
```

在仓库根目录（`05-annotation/`）跑。`node_modules` 会落在工作目录里，
**别提交**（已在 .gitignore）。

## chsims 中文文本的英译

`chsims` 的文本素材全是中文（914 条 / 931 句），而标注者未必懂中文——
看不懂的文本模态等于让人凭空猜。用 Gemini 译成英文，**中英并排滚动**：
中文逐词点亮、英文整句跟着本句首词一起亮（中英词序不同，逐词对齐做不到，
硬对齐只会把译文切成看不懂的碎片）。

```bash
export GEMINI_API_KEY=...
python3 src/translate_text.py --limit 5 --print   # 先看几条
python3 src/translate_text.py                     # 全量，约 15 分钟
python3 src/check_translations.py                 # 质检
```

### 为什么分两遍

译文是**情绪判断的唯一依据**，一个词的强弱直接落到标注尺度上：
「没」译成 never 而非 not，负向就被拔高一档。一次定稿时模型会偏向通顺，
而通顺常常意味着替说话人加了语气。所以：

1. 第一遍同时给出 `literal`（逐字平淡）与 `idiomatic`（地道自然）
2. 第二遍把原文与两版一起交回评审，选**情感强度与原文最贴**的那版

评审 prompt 里最要紧的一句是：**「它更能传达语气」是拒绝一个版本的理由，
不是选择它的理由**。第一版没写这句，结果它挑中了 "Stop dreaming"
（原文「别做梦了」是劝阻不是呵斥），理由写着「更好地传达了轻蔑语气」。

两个候选、选择与理由都留在 `transcripts_v3/`，上传时才剥掉——
抽查看得见它为什么这么选，改主意也不必重译。

### 质检看什么

`check_translations.py` 不下结论，只把高风险的排前面：凭空的强化词、
凭空的感叹号、长度失衡。**授权表要够宽**：第一版只收「真/太/好」，
结果 30 条里全是「都→even」「不得了→extremely」这类标准译法，
真问题反而浮不上来。

全量结果：强化词 12 条（多数站得住）、感叹号 0 条、长度失衡 59 条
（全是短句被小分母放大）。平淡 / 地道选用比 53% / 47%——两个候选
确实在分工。
