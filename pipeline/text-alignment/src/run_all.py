"""全量词级对齐。分片、可断点续跑。

样本清单取 06 交付的 3440 条 manifest，不是 3500 池——被剔除的 60 条不进标注，
对齐它们是白费。
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from datapaths import FRAMES_DIR, stage_path  # noqa: E402

sys.path.insert(0, str(stage_path("speaker-frames")))

from align import (  # noqa: E402
    ChineseAligner,
    EnglishAligner,
    extract_audio,
    tokenize,
)
from resolve import resolve  # noqa: E402

DELIVERY = FRAMES_DIR / "out" / "manifest.jsonl"


def delivered() -> list[tuple[str, str]]:
    rows = [json.loads(line) for line in DELIVERY.open(encoding="utf-8")]
    return [(r["sample_id"], r["source"]) for r in rows]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--of", type=int, default=1)
    parser.add_argument("--out-dir", default=str(ALIGN_DIR / "out" / "align"))
    args = parser.parse_args()

    samples = [
        pair
        for index, pair in enumerate(delivered())
        if index % args.of == args.shard
    ]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"shard-{args.shard:02d}.jsonl"

    done = set()
    if out_path.exists():
        for line in out_path.open(encoding="utf-8"):
            done.add(json.loads(line)["sample_id"])

    english = chinese = None
    written = 0
    with out_path.open("a", encoding="utf-8") as handle:
        for sample_id, source in samples:
            if sample_id in done:
                continue
            record = {"sample_id": sample_id, "source": source}
            try:
                info = resolve(sample_id, source)
                text = (info["extra"]["text"] or "").strip()
                if not text:
                    raise ValueError("转录稿为空")
                waveform = extract_audio(info["video_path"])
                is_chinese = source == "chsims"
                units = tokenize(text, chinese=is_chinese)
                if is_chinese:
                    chinese = chinese or ChineseAligner()
                    aligned = chinese.align(waveform, units)
                else:
                    english = english or EnglishAligner()
                    aligned = english.align(waveform, units)
                record |= {
                    "status": "ok",
                    "duration": round(waveform.size(1) / 16000, 3),
                    "text": text,
                    "words": [
                        {"t": w.text, "s": w.start, "e": w.end, "c": w.score}
                        for w in aligned
                    ],
                }
            except Exception as error:
                record |= {
                    "status": "failed",
                    "error": f"{type(error).__name__}: {error}",
                }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            written += 1
            if written % 25 == 0:
                print(f"[shard {args.shard}] {written}/{len(samples)}", flush=True)

    print(f"[shard {args.shard}] 完成，本次写入 {written}", flush=True)


if __name__ == "__main__":
    main()
