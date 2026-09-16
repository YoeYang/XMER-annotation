"""产出 05-annotation 的导入清单：每个样本展开成四个模态任务。

模态顺序在服务端另有保证（`api.py` 的 MODALITY_RANK），这里只管内容。
姓名用 05 的 `clean_speaker_name()` 清洗，避免占位符进库。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from datapaths import MEDIA_DIR, REPO_ROOT  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "server"))
from app.assignments import clean_speaker_name  # noqa: E402

OUT = MEDIA_DIR / "out"
BASE = "/pool"  # 独立于 annotation-static：前端部署的 rsync --delete 不会波及素材

MODALITIES = [
    ("visual", "仅视觉", "media/{sid}/visual.mp4",
     "只看画面，不受台词与语气影响，判断目标人物的情绪表达。"),
    ("audio", "仅音频", "media/{sid}/audio.m4a",
     "只听语气语调，不看画面。"),
    ("text", "仅文本", "transcripts/{sid}.json",
     "只看逐词呈现的转录文字。时间戳由强制对齐得到，跟随真实语速与停顿。"),
    ("audiovisual", "完整视频", "media/{sid}/audiovisual.mp4",
     "完整原始片段（画面+语气+台词同时呈现）。"),
]


def main() -> None:
    prepared = []
    for shard in sorted(OUT.glob("prepared-*.jsonl")):
        for line in shard.open(encoding="utf-8"):
            record = json.loads(line)
            if record["status"] == "ok":
                prepared.append(record)
    prepared.sort(key=lambda r: r["sample_id"])

    tasks = []
    for row in prepared:
        sid = row["sample_id"]
        speaker = clean_speaker_name(row.get("speaker_name"))
        frame = OUT / "media" / sid / "speaker.jpg"
        for modality, label, template, target in MODALITIES:
            tasks.append(
                {
                    "task_id": f"{sid}::{modality}",
                    "media_id": f"{sid}-{modality}",
                    "source_id": sid,
                    "title": f"{sid} · {label}",
                    "modality": modality,
                    "src": f"{BASE}/{template.format(sid=sid)}",
                    "duration": row["duration"],
                    "target": target,
                    "demo": False,
                    "timeline_origin": 0,
                    "speaker_ref_src": (
                        f"{BASE}/media/{sid}/speaker.jpg" if frame.exists() else None
                    ),
                    "speaker_name": speaker,
                }
            )

    dest = OUT / "tasks_import.json"
    dest.write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")

    named = sum(1 for t in tasks if t["speaker_name"])
    framed = sum(1 for t in tasks if t["speaker_ref_src"])
    print(f"样本 {len(prepared)} → 任务 {len(tasks)}")
    print(f"  带静帧 {framed}，带姓名 {named}")
    print(f"  写入 {dest}（{dest.stat().st_size / 1024 / 1024:.1f} MB）")


if __name__ == "__main__":
    main()
