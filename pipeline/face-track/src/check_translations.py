"""译文质检：找出可能被加进去的情感色彩。

翻译的唯一要求是不增删情感强度，但这件事没法自动判定——只能把**高风险的
迹象**捞出来给人看。这个脚本不下结论，只排序：把最可能出问题的排在前面。

三类迹象：

1. **强化词**：so / really / such / totally… 中文很少授权这些词，
   出现一次就值得看一眼原文有没有对应的成分
2. **感叹号**：原文没有「！」而译文有，是凭空加的语气
3. **长度失衡**：译文词数远超汉字数的一半，多半在扩写；远低于则可能漏译

用法：

    python3 src/check_translations.py            # 打印各类前 20 条
    python3 src/check_translations.py --all      # 全部列出
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "out"
TRANSCRIPTS = ROOT / "transcripts_v3"

# 中文极少授权这些词。不是说出现就一定错——"真的" 确实对应 really——
# 而是出现时值得回头看一眼原文有没有对应成分。
INTENSIFIERS = [
    "so", "such", "really", "totally", "absolutely", "completely",
    "even", "ever", "never", "damn", "terrible", "wonderful", "awful",
    "extremely", "incredibly", "utterly",
]
# 这些中文成分本来就对应强化词，配对出现时不算问题。
# 表窄了会淹没真问题：第一版只收了「真/太/好」，结果 30 条里全是
# 「都→even」「不得了→extremely」这类标准译法，真要看的那几条根本浮不上来。
LICENSED = {
    "really": ["真", "确实", "实在", "可", "着实"],
    # 「死了」「极了」「透了」是口语强化，对应 so 是合理的
    "so": ["这么", "那么", "太", "好", "如此", "死了", "极了", "透了"],
    "such": ["这么", "那么", "如此"],
    "never": ["从来", "从没", "永远", "绝不", "横竖", "没", "不曾"],
    "completely": ["完全", "彻底", "殆尽", "全"],
    "totally": ["完全", "整个", "彻底"],
    "absolutely": ["绝对", "绝", "千万", "一定", "务必"],
    # 「都」「就算」「连」「甚至」→ even 是汉英最常见的对应之一
    "even": ["都", "就算", "即使", "连", "甚至", "还", "也"],
    "ever": ["从来", "自从", "曾", "过"],
    "extremely": ["极", "非常", "不得了", "得很", "十分"],
    "incredibly": ["极", "非常", "不得了"],
    "utterly": ["完全", "彻底"],
    "terrible": ["糟", "可怕", "惨", "差"],
    "awful": ["糟", "可怕", "惨"],
    "wonderful": ["好极", "棒", "美妙"],
    "damn": ["该死", "他妈"],
}

def scan():
    rows = []
    for path in sorted(TRANSCRIPTS.glob("chsims_*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        for sentence in record["sentences"]:
            zh, en = sentence.get("text_zh", ""), sentence.get("text_en", "")
            if not zh or not en:
                continue
            rows.append((path.stem, zh, en, sentence.get("en_choice", "")))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    rows = scan()
    if not rows:
        raise SystemExit("还没有译文")

    words = re.compile(r"[a-z']+")
    flagged, bangs, skewed = [], [], []
    picks = Counter()
    for sample, zh, en, choice in rows:
        picks[choice] += 1
        low = set(words.findall(en.lower()))
        for word in INTENSIFIERS:
            if word not in low:
                continue
            # so 当连词（「所以/就」）与当强化词（so annoying）是两回事，
            # 只看词形会把前者全报出来。连词位置在句首或紧跟逗号。
            if word == "so" and not re.search(r"\bso +[a-z]+(ly)?\b(?! +[A-Z])", en)\
                    and (en.startswith("So ") or ", so " in en or ". So " in en):
                continue
            # 原文有对应成分就不算凭空添加
            if any(cue in zh for cue in LICENSED.get(word, [])):
                continue
            flagged.append((word, sample, zh, en))
        if "!" in en and "！" not in zh:
            bangs.append((sample, zh, en))
        ratio = len(en.split()) / max(1, len(zh))
        if ratio > 0.95 or ratio < 0.3:
            skewed.append((ratio, sample, zh, en))

    total = sum(picks.values())
    print(f"共 {total} 句　平淡 {picks['literal']}"
          f"（{picks['literal']/total:.0%}）、"
          f"地道 {picks['idiomatic']}（{picks['idiomatic']/total:.0%}）\n")

    def show(title, items, fmt, limit=20):
        print(f"── {title}：{len(items)} 条 " + "─" * 40)
        for item in (items if args.all else items[:limit]):
            print(fmt(item))
        if not args.all and len(items) > limit:
            print(f"   …… 另有 {len(items) - limit} 条，--all 看全部")
        print()

    show("疑似凭空添加的强化词", sorted(flagged),
         lambda r: f"  [{r[0]}] {r[2]}\n        {r[3]}")
    show("原文无「！」而译文有", bangs,
         lambda r: f"  {r[1]}\n        {r[2]}")
    show("长度失衡（词数/字数 >0.95 或 <0.3）", sorted(skewed, reverse=True),
         lambda r: f"  [{r[0]:.2f}] {r[2]}\n        {r[3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
