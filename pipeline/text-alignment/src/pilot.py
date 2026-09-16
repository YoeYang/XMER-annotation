"""小样本试跑：对齐一批样本并评估质量。

质量判据**不用平均置信度**。CTC 对 "you"、"don't" 这类短功能词的声学置信度
天然很低，但只要夹在两个高分词之间，时间就是对的。真正有判别力的是：

  in_speech  词是否落在能量意义上的有声区间内
  monotonic  词序是否随时间单调（对齐崩掉时会乱序或全部挤在一起）
  span_ratio 词覆盖的时长占整段有声时长的比例，过低说明漏掉了大段语音
"""

import argparse
import json
import random
import statistics
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from datapaths import stage_path  # noqa: E402

sys.path.insert(0, str(stage_path("speaker-frames")))

from align import EnglishAligner, Word, extract_audio, tokenize  # noqa: E402
from resolve import load_pool, resolve  # noqa: E402

HOP = 1600  # 0.1 秒


def speech_spans(waveform, threshold_ratio: float = 0.12):
    """按能量粗切有声区间。不是 VAD——笑声、别人说话同样会被算作有声，
    所以它只用来判断"词有没有落在完全静音处"，不用来判断"是不是目标说话人"。"""
    x = waveform[0].numpy()
    frames = np.sqrt(
        np.array([(x[i : i + HOP] ** 2).mean() for i in range(0, len(x) - HOP, HOP)])
    )
    if not len(frames) or frames.max() == 0:
        return [], frames
    threshold = frames.max() * threshold_ratio
    spans, start = [], None
    for i, value in enumerate(frames):
        if value > threshold and start is None:
            start = i
        elif value <= threshold and start is not None:
            spans.append((start / 10, i / 10))
            start = None
    if start is not None:
        spans.append((start / 10, len(frames) / 10))
    return spans, frames


def assess(words: list[Word], spans, duration: float) -> dict:
    if not words:
        return {"word_count": 0, "in_speech": 0.0, "monotonic": True, "span_ratio": 0.0}
    inside = sum(
        any(a - 0.15 <= w.start <= b + 0.15 for a, b in spans) for w in words
    )
    starts = [w.start for w in words]
    speech_total = sum(b - a for a, b in spans) or duration
    return {
        "word_count": len(words),
        "in_speech": round(inside / len(words), 3),
        "monotonic": starts == sorted(starts),
        "span_ratio": round((words[-1].end - words[0].start) / speech_total, 3),
        "mean_score": round(statistics.mean(w.score for w in words), 3),
        "silent_tail": round(
            max((b - a for a, b in spans if a >= words[-1].end), default=0.0), 2
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-source", type=int, default=20)
    parser.add_argument("--sources", default="meld,mustard,iemocap,mosi")
    parser.add_argument("--seed", type=int, default=20260913)
    parser.add_argument("--out", default=str(ALIGN_DIR / "out" / "pilot.jsonl"))
    args = parser.parse_args()

    wanted = args.sources.split(",")
    by_source: dict[str, list[str]] = {}
    for sample_id, source in load_pool():
        if source in wanted:
            by_source.setdefault(source, []).append(sample_id)

    rng = random.Random(args.seed)
    picked = [
        (sample_id, source)
        for source in wanted
        for sample_id in rng.sample(
            by_source.get(source, []), min(args.per_source, len(by_source.get(source, [])))
        )
    ]

    aligner = EnglishAligner()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8") as handle:
        for sample_id, source in picked:
            record = {"sample_id": sample_id, "source": source}
            try:
                info = resolve(sample_id, source)
                text = (info["extra"]["text"] or "").strip()
                if not text:
                    raise ValueError("转录稿为空")
                waveform = extract_audio(info["video_path"])
                duration = waveform.size(1) / 16000
                spans, _ = speech_spans(waveform)
                words = aligner.align(waveform, tokenize(text, chinese=False))
                record |= {
                    "status": "ok",
                    "duration": round(duration, 2),
                    "text": text,
                    "speech_spans": [[round(a, 2), round(b, 2)] for a, b in spans],
                    "words": [
                        {"t": w.text, "s": w.start, "e": w.end, "c": w.score}
                        for w in words
                    ],
                    **assess(words, spans, duration),
                }
            except Exception as error:
                record |= {"status": "failed", "error": f"{type(error).__name__}: {error}"}
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            print(
                f"{sample_id:38s} {record.get('status')} "
                f"in_speech={record.get('in_speech', '-')}",
                flush=True,
            )


if __name__ == "__main__":
    main()
