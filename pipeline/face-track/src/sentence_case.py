#!/usr/bin/env python3
"""把全大写的转录稿改成句首大写。

MOSI 的原始转录稿整篇是大写（`AND THE OTHER HORRIBLE I MEAN…`）。
标注文本模态时这些字要逐词点亮读一遍，全大写读起来很累，且大写本身
会被读成强调——而这一轮要标的恰恰是情绪强度，不能让排版先给出暗示。

只动**整句都是大写**的句子：MELD、IEMOCAP、mustard 的转录稿本来就是
正常大小写，碰了反而会破坏专有名词。
"""
import json
import sys
from pathlib import Path

# 小写化之后要还原的独立词
KEEP_UPPER = {"i", "i'm", "i've", "i'll", "i'd", "tv", "dvd", "ok", "us", "uk"}


def recase_tokens(tokens: list[dict]) -> bool:
    """返回是否改动过。tokens 按出现顺序，第一个词首字母大写。"""
    words = [t["text"] for t in tokens]
    letters = "".join(w for w in words if w.isalpha() or "'" in w)
    if not letters or not letters.isupper():
        return False
    for index, token in enumerate(tokens):
        low = token["text"].lower()
        if low.startswith("i") and low in KEEP_UPPER:
            word = "I" + low[1:]          # i / i'm / i've
        elif low in KEEP_UPPER:
            word = low.upper()            # TV / DVD / OK
        else:
            word = low
        if index == 0 and word[:1].isalpha():
            word = word[0].upper() + word[1:]
        token["text"] = word
    return True


def recase_file(path: Path) -> bool:
    doc = json.loads(path.read_text(encoding="utf-8"))
    changed = False
    for sentence in doc.get("sentences", []):
        if recase_tokens(sentence.get("tokens", [])):
            changed = True
    if changed:
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return changed


if __name__ == "__main__":
    total = 0
    for root in sys.argv[1:]:
        hits = sum(recase_file(p) for p in sorted(Path(root).glob("*.json")))
        print(f"{root}: 改写 {hits} 份")
        total += hits
    print(f"共 {total} 份")
