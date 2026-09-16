"""产出 V3 的导入清单：每个样本展开成**五个**模态子任务。

取代 `material-prep/src/build_tasks.py`（那份是四模态、读旧素材的，已被本文件超越）。
两处关键差别：

1. **`visual` 拆成 `face` 与 `body`**，模态从 4 个变成 5 个
2. **时长与素材都取自 `media_v3`**，那是五路对齐过的版本；
   旧素材的时长在五路之间最大差 0.700s，不能再用

线上路径用 `/pool/v3/` 前缀与旧素材并存，切换前老链接不会断。

> 导入前必须先做后端改造：`server/app/config.py` 的 `MODALITIES` 还是
> 四个值，`tasks` 表的 CheckConstraint 会直接拒绝 `face` / `body`。
"""
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
    builds = sorted(MEDIA_V3.glob("*/build.json"))

    tasks, missing_transcript, missing_frame = [], [], 0
    for b in builds:
        rec = json.loads(b.read_text(encoding="utf-8"))
        sid = rec["sample_id"]
        duration = rec["duration"]
        speaker = clean_speaker_name(names.get(sid))
        # 静帧仍在 06 的产物里，部署时随 media_v3 一起同步（见 README）
        frame = MEDIA_V3 / sid / "speaker.jpg"
        if not frame.exists():
            missing_frame += 1
        if not (TRANSCRIPTS_V3 / f"{sid}.json").exists():
            missing_transcript.append(sid)

        for modality, label, template, target in MODALITIES:
            tasks.append({
                "task_id": f"{sid}::{modality}",
                "media_id": f"{sid}-{modality}",
                "source_id": sid,
                "title": f"{sid} · {label}",
                "modality": modality,
                "src": f"{BASE}/{template.format(sid=sid)}",
                "duration": duration,
                "target": target,
                "demo": False,
                "timeline_origin": 0,
                "speaker_ref_src": (f"{BASE}/media/{sid}/speaker.jpg"
                                    if frame.exists() else None),
                "speaker_name": speaker,
            })

    dest = ROOT / "tasks_import_v3.json"
    dest.write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")

    named = sum(1 for t in tasks if t["speaker_name"])
    framed = sum(1 for t in tasks if t["speaker_ref_src"])
    print(f"样本 {len(builds)} 条 × {len(MODALITIES)} 模态 = {len(tasks)} 个子任务")
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
