"""把对齐结果转成标注页要求的转录稿格式。

标注页的 `validateTranscript` 校验很严，任何一条不满足就整个任务加载失败：

  - `doc.duration` 必须**恰好等于**任务时长
  - 句子之间不重叠且递增，`end > start`，`end <= duration`
  - 句内 token 递增不重叠，**`end > start`（零时长会被拒）**，`end <= sentence.end`

对齐结果直接倒出来是不满足的：插值定位的标点就是零时长。所以这里做一次
规整，并用同一套规则在 Python 侧复核一遍，避免 3440 个文件里混进坏的。
"""

import re

MIN_WIDTH = 0.04  # 单个 token 的最小时长，秒
TERMINALS = set(".!?。！？…")


def split_sentences(words: list[dict]) -> list[list[dict]]:
    """按句末标点切句。切不出来就整段作一句。"""
    sentences, current = [], []
    for word in words:
        current.append(word)
        if word["t"] and word["t"].strip()[-1:] in TERMINALS:
            sentences.append(current)
            current = []
    if current:
        sentences.append(current)
    return sentences or [words]


def _normalise(words: list[dict], limit: float) -> list[tuple[str, float, float]]:
    """强制递增、不重叠、每个 token 时长为正，整体不超过 limit。"""
    out: list[tuple[str, float, float]] = []
    cursor = 0.0
    for word in words:
        start = max(float(word["s"]), cursor)
        end = max(float(word["e"]), start + MIN_WIDTH)
        out.append((word["t"], start, end))
        cursor = end

    # 规整后若超出媒体时长，整体等比压缩：保序、保正时长，只是节奏略快
    overflow = out[-1][2] if out else 0.0
    if overflow > limit and overflow > 0:
        scale = limit / overflow
        out = [(t, s * scale, e * scale) for t, s, e in out]
    return out


def build(words: list[dict], duration: float) -> dict:
    """产出可直接落盘的转录稿。"""
    normalised = _normalise(words, duration)
    groups = split_sentences(
        [{"t": t, "s": s, "e": e} for t, s, e in normalised]
    )

    sentences = []
    for group in groups:
        tokens = [
            {"start": round(w["s"], 3), "end": round(w["e"], 3), "text": w["t"]}
            for w in group
        ]
        sentences.append(
            {
                "start": tokens[0]["start"],
                "end": tokens[-1]["end"],
                "tokens": tokens,
            }
        )
    return {"duration": duration, "sentences": sentences}


def validate(doc: dict, duration: float) -> None:
    """`validateTranscript` 的 Python 镜像。不通过就抛，别让坏文件上线。"""
    if doc["duration"] != duration:
        raise ValueError(f"时长不符 {doc['duration']} != {duration}")
    previous = 0.0
    for sentence in doc["sentences"]:
        if not (
            sentence["start"] >= previous
            and sentence["end"] > sentence["start"]
            and sentence["end"] <= duration
            and sentence["tokens"]
        ):
            raise ValueError(f"句子时间戳无效: {sentence['start']}–{sentence['end']}")
        cursor = sentence["start"]
        for token in sentence["tokens"]:
            if not (
                token["start"] >= cursor
                and token["end"] > token["start"]
                and token["end"] <= sentence["end"]
                and isinstance(token["text"], str)
                and token["text"]
            ):
                raise ValueError(f"token 时间戳无效: {token}")
            cursor = token["end"]
        previous = sentence["end"]
