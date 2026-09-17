"""产出 V3 的导入清单：每个样本展开成**五个**模态子任务。

取代 `material-prep/src/build_tasks.py`（那份是四模态、读旧素材的，已被本文件超越）。
两处关键差别：

1. **`visual` 拆成 `face` 与 `body`**，模态从 4 个变成 5 个
2. **时长与素材都取自 `media_v3`**，那是五路对齐过的版本；
   旧素材的时长在五路之间最大差 0.700s，不能再用

线上路径用 `/pool/v3/` 前缀与旧素材并存，切换前老链接不会断。

**对外一律用 display_id，绝不出现原始样本名。** `display_id` 的整套机制就是
不让标注者知道样本出处，但 `src` / `task_id` / `media_id` 里一旦带上
`meld_dia17_utt6` 这种名字，打开开发者工具或右键视频就全看见了——编号
等于白发。`source_id` 只作为后台字段留在库里，不随 `TaskOut` 下发。

> 导入前必须先做后端改造：`server/app/config.py` 的 `MODALITIES` 还是
> 四个值，`tasks` 表的 CheckConstraint 会直接拒绝 `face` / `body`。
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from datapaths import FRAMES_DIR, REPO_ROOT  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "server"))
from app.assignments import clean_speaker_name  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "out"
MEDIA_V3 = ROOT / "media_v3"
TRANSCRIPTS_V3 = ROOT / "transcripts_v3"
MANIFEST = FRAMES_DIR / "out" / "manifest.jsonl"
FRAMES = FRAMES_DIR / "out" / "frames"
DISPLAY_IDS = REPO_ROOT / "server" / "plans" / "display_ids.csv"
DROPPED = ROOT / "dropped.txt"

BASE = "/pool/v3"

MODALITIES = [
    ("face", "仅面部", "media/{sid}/face.mp4",
     "只看说话人的面部表情。认不出说话人的时段是黑屏，那是正常的。"),
    ("body", "仅身体", "media/{sid}/body.mp4",
     "只看说话人的身体动作与姿态，面部已被遮住。被遮住的那个人就是要判断的对象。"),
    ("audio", "仅音频", "media/{sid}/audio.m4a",
     "只听语气语调，不看画面。"),
    ("text", "仅文本", "transcripts/{sid}.json",
     "只看逐词呈现的转录文字。时间戳由强制对齐得到，跟随真实语速与停顿。"),
    ("audiovisual", "完整视频", "media/{sid}/audiovisual.mp4",
     "完整原始片段（画面+语气+台词同时呈现）。"),
]


def display_ids() -> dict[str, str]:
    """样本 → 对标注者可见的编号。

    编号一旦发出就不能变，也不能回收重发：老编号指向新样本的话，
    先前提交的结果会对到错的样本上。所以这里只读不发号，
    发号仍由 `manage.py assign-display-ids` 负责。
    """
    with DISPLAY_IDS.open(encoding="utf-8") as f:
        return {row["source_id"]: row["display_id"] for row in csv.DictReader(f)}


def dropped() -> set[str]:
    if not DROPPED.exists():
        return set()
    return {line.strip() for line in DROPPED.read_text(encoding="utf-8").split() if line.strip()}


def speaker_names():
    names = {}
    with MANIFEST.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                names[rec["sample_id"]] = rec.get("speaker_name")
    return names


def main():
    names = speaker_names()
    numbers = display_ids()
    skip = dropped()
    builds = sorted(MEDIA_V3.glob("*/build.json"))

    tasks, missing_transcript, missing_frame = [], [], 0
    unnumbered, excluded = [], 0
    for b in builds:
        rec = json.loads(b.read_text(encoding="utf-8"))
        sid = rec["sample_id"]
        if sid in skip:
            # 人工质检判死的，整条剔除——不做「按子任务剔除」，
            # 一个样本必须五个模态齐全，否则跨模态没法比
            excluded += 1
            continue
        code = numbers.get(sid)
        if code is None:
            # 缺编号就只能露出原始名，宁可停下来也不要悄悄泄露出处
            unnumbered.append(sid)
            continue
        duration = rec["duration"]
        speaker = clean_speaker_name(names.get(sid))
        # 静帧直接读 06 的产物，不在 media_v3 里另存一份——129MB 复制两遍
        # 只为省一次路径拼接不划算，多一个步骤还多一处会忘记跑的地方。
        # 上传时由 stage_upload.py 从同一处取。
        frame = FRAMES / f"{sid}.jpg"
        if not frame.exists():
            missing_frame += 1
        if not (TRANSCRIPTS_V3 / f"{sid}.json").exists():
            missing_transcript.append(sid)

        for modality, label, template, target in MODALITIES:
            tasks.append({
                "task_id": f"{code}::{modality}",
                "media_id": f"{code}-{modality}",
                # 后台字段，`TaskOut` 不下发；导出与分析靠它回到原始样本
                "source_id": sid,
                # 编号随清单一起进库。不带的话，导入后 `display_id` 是空的，
                # `assign-display-ids` 会把这些样本当成没编号而**重新发号**，
                # 于是 task_id 写着 S0123、编号却变成了 S0456。
                "display_id": code,
                "title": f"{sid} · {label}",
                "modality": modality,
                "src": f"{BASE}/{template.format(sid=code)}",
                "duration": duration,
                "target": target,
                "demo": False,
                "timeline_origin": 0,
                "speaker_ref_src": (f"{BASE}/media/{code}/speaker.jpg"
                                    if frame.exists() else None),
                "speaker_name": speaker,
            })

    if unnumbered:
        raise SystemExit(
            f"有 {len(unnumbered)} 条样本没有编号，无法生成清单："
            f"{unnumbered[:5]}\n"
            "先跑 manage.py assign-display-ids 发号并导出 display_ids.csv。"
        )

    dest = ROOT / "tasks_import_v3.json"
    dest.write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")

    named = sum(1 for t in tasks if t["speaker_name"])
    framed = sum(1 for t in tasks if t["speaker_ref_src"])
    print(f"样本 {len(tasks)//len(MODALITIES)} 条 × {len(MODALITIES)} 模态 "
          f"= {len(tasks)} 个子任务（建出 {len(builds)}，剔除 {excluded}）")
    print(f"  有说话人姓名的: {named}")
    print(f"  有静帧的:       {framed}")
    if missing_frame:
        print(f"  ⚠ 缺静帧: {missing_frame} 条（先跑 copy_speaker_frames）")
    if missing_transcript:
        print(f"  ⚠ 缺转录稿: {len(missing_transcript)} 条 "
              f"{missing_transcript[:5]}")
    print(f"→ {dest}")


if __name__ == "__main__":
    main()
