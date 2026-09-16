"""把转录稿的词级时间戳对齐到 V3 的新媒体时长。

## 为什么要改

五路对齐时取的是「共同覆盖的最短时长」，素材尾部被截掉了一点
（中位 0.033s，最大 0.720s）。转录稿的时间戳是按**原始**素材算的，
于是有 396 条样本（11.7%）的末词结束时间跑到了新媒体时长之外。

后果：文本模态按媒体时间推进高亮，越界的词**永远不会被点亮**。
实测有 143 个词的起始时间已完全落到媒体之外，其中 118 个是标点（无所谓），
但另外 25 个是真字——包括语气词（啊/呢/吧/吗，中文里带情绪）
和被砍掉末字的多字词（「情况」→「情」、「生气」→「生」），
还有一个完整的「滚」。

## 怎么改：整体前移，一个词都不丢

**不删词**，把越界的词左移，让它刚好卡进新时长内，各自保持原有时长。
**从后往前**处理：末词先靠到新时长的右边界，再依次往前推，
这样连续越界的几个词不会挤成一堆。

最大位移 0.092 秒——而 handover 记着人的反应延迟是几百毫秒，
这个偏差察觉不到。代价只是那 25 条样本的末尾一两个字比语音早 0.09 秒以内亮起，
这比丢掉「滚」字划算得多。

> 截的一直是**尾部**，开头原样保留（已用逐帧像素比对实证过）。
> 时间轴原点必须留在 0，否则转录稿、静帧、采样点的时间戳全要平移。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from datapaths import MEDIA_DIR

ROOT = Path(__file__).resolve().parents[1] / "out"
MEDIA_V3 = ROOT / "media_v3"
SRC_TRANSCRIPTS = MEDIA_DIR / "out" / "transcripts"
OUT = ROOT / "transcripts_v3"

EPS = 1e-6


def shift_tokens(tokens, duration):
    """从后往前把越界的词移进 [0, duration]，各自保持原时长。

    返回 (新 token 列表, 被移动的个数, 最大位移)。
    """
    spans = []
    limit = duration
    for t in reversed(tokens):
        start, end = float(t["start"]), float(t["end"])
        width = max(0.0, end - start)
        new_end = min(end, limit)
        new_start = new_end - width
        if new_start < 0:                     # 整条都塞不下，只能压缩
            new_start, new_end = 0.0, min(width, limit)
        spans.append((new_start, new_end))
        limit = new_start
    spans.reverse()

    moved, max_shift = 0, 0.0
    out = []
    for t, (s, e) in zip(tokens, spans):
        shift = abs(float(t["start"]) - s)
        if shift > EPS:
            moved += 1
            max_shift = max(max_shift, shift)
        out.append({**t, "start": round(s, 3), "end": round(e, 3)})
    return out, moved, max_shift


def fix(sample_id, duration):
    src = SRC_TRANSCRIPTS / f"{sample_id}.json"
    if not src.exists():
        return None, "transcript_missing"
    doc = json.loads(src.read_text(encoding="utf-8"))

    moved_total, max_shift = 0, 0.0
    for sentence in doc.get("sentences", []):
        toks = sentence.get("tokens") or []
        if not toks:
            continue
        new_toks, moved, shift = shift_tokens(toks, duration)
        sentence["tokens"] = new_toks
        sentence["start"] = new_toks[0]["start"]
        sentence["end"] = new_toks[-1]["end"]
        moved_total += moved
        max_shift = max(max_shift, shift)

    doc["duration"] = round(duration, 3)

    # 硬断言：一个词都不能越界，且时间必须单调不减
    prev = -1.0
    for sentence in doc.get("sentences", []):
        for t in sentence.get("tokens", []):
            if t["end"] > duration + 1e-3:
                return None, f"越界 {t['text']} end={t['end']} > {duration}"
            if t["start"] < prev - 1e-3:
                return None, f"非单调 {t['text']} start={t['start']} < {prev}"
            prev = t["start"]

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{sample_id}.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return {"moved": moved_total, "max_shift": round(max_shift, 4)}, None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--samples", default="")
    args = ap.parse_args()

    builds = sorted(MEDIA_V3.glob("*/build.json"))
    if args.samples:
        wanted = set(Path(args.samples).read_text().split())
        builds = [b for b in builds if b.parent.name in wanted]

    from collections import Counter
    tally, moved_samples, shifts, fails = Counter(), 0, [], []
    for b in builds:
        rec = json.loads(b.read_text(encoding="utf-8"))
        info, err = fix(rec["sample_id"], rec["duration"])
        if err:
            tally["fail"] += 1
            fails.append(f"{rec['sample_id']}: {err}")
            continue
        tally["ok"] += 1
        if info["moved"]:
            moved_samples += 1
            shifts.append(info["max_shift"])

    print("完成:", dict(tally))
    print(f"有词被前移的样本: {moved_samples}/{tally['ok']}")
    if shifts:
        s = sorted(shifts)
        q = lambda p: s[min(len(s) - 1, int(len(s) * p))]
        print(f"最大位移: 中位={q(.5):.4f}s p90={q(.9):.4f}s 最大={s[-1]:.4f}s")
    for m in fails[:20]:
        print("  失败:", m)


if __name__ == "__main__":
    main()
