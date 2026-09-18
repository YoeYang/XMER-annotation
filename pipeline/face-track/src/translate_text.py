"""把中文转录稿译成英文，供文本模态双语呈现。

## 为什么要译

`chsims` 的文本素材全是中文（914 条样本 / 931 句）。标注者未必懂中文，
但都懂英文——看不懂的文本模态等于让人凭空猜，标出来的是噪音。

## 为什么翻译质量在这里格外要紧

译文是**情绪判断的唯一依据**。一个词的强弱差别会直接落到标注尺度上：

* 「没」译成 `never` 而不是 `not`，负向被拔高了一档
* 「算了」译成 `forget it!` 而不是 `never mind`，凭空多了怒气
* 「挺好的」译成 `it's great!` 而不是 `it's fine`，正向被拔高了

所以 prompt 反复申明的只有一件事：**不要增删任何情感色彩**。宁可译得平淡
生硬，也不要译得地道传神——地道往往意味着译者替说话人加了语气。

## 两遍：先出两个候选，再评审选一个

一次定稿要模型同时兼顾"忠实"和"通顺"，它往往偏向通顺——而通顺常常
意味着替说话人加了语气。所以拆成两步：

1. **第一遍**同时给出 `literal`（逐字平淡）与 `idiomatic`（地道自然）两版
2. **第二遍**把原文和两版一起交回去评审，选情感强度与原文最贴的那个，
   并写下一句理由

两个候选都留在文件里，评审的选择和理由也留着——抽查时看得见它为什么
这么选，改主意时不必重译。

## 对齐方式

中英词序不同，逐词对齐做不到，也不必做：**按句对齐**。每句译文继承原句的
起止时间，播放时中文逐词点亮、英文整句点亮。句子是情绪的自然单位，
词级对齐反而会把译文切碎成看不懂的碎片。

用法：

    export GEMINI_API_KEY=...
    python3 src/translate_text.py            # 跑全部，已有译文的跳过
    python3 src/translate_text.py --limit 5  # 先试几条看看
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "speaker-frames" / "src"))

from gemini_client import Gemini  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "out"
TRANSCRIPTS = ROOT / "transcripts_v3"

# ---------------------------------------------------------------- prompt

DRAFT_SYSTEM = """You translate Chinese speech transcripts into English for an emotion-annotation study.

Annotators read your translation and rate how the speaker feels, so your wording
decides what they see. Produce TWO versions of the same line:

- "literal": word-by-word, deliberately plain. Prefer awkward English over
  smooth English. Add nothing the speaker did not say.
- "idiomatic": what a careful translator would write for a subtitle — natural
  English, but still with **no emotional colouring that the Chinese lacks**.

Rules that bind BOTH versions:

1. Never add intensifiers absent from the source. 好 is "good", not "great".
   没 is "not", not "never" or "hardly".
2. Never add exclamation marks; never turn a statement into an exclamation.
   Keep source punctuation, including 。，？！and ellipses.
3. Sentence-final particles (吧 呢 啊 吗 嘛) carry tone, not content. Render
   their grammatical function only — a question particle becomes a question
   mark — never as emotive words like "come on" or "you know".
4. Do not resolve ambiguity toward the more vivid reading. When in doubt,
   take the flattest one.
5. Keep proper names and numbers exactly.
6. Fragments stay fragments. Never complete an unfinished sentence.
7. **Keep the English close in length to the Chinese.** The two are shown
   side by side and highlighted together while the clip plays, so a
   translation twice as long drifts out of sync with what is being said.
   Roughly one English word per Chinese character is the target. When two
   wordings are equally faithful, always take the shorter one. Drop
   padding like "in the", "there is", "the fact that" wherever grammar allows.

The two versions may be identical if the line is simple."""

DRAFT_TEMPLATE = """Chinese transcript line:
{text}"""

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "literal": {"type": "string", "description": "逐字直译，宁可生硬"},
        "idiomatic": {"type": "string", "description": "地道但不加情感色彩"},
    },
    "required": ["literal", "idiomatic"],
}

JUDGE_SYSTEM = """You are checking two English translations of one Chinese line
that will be shown to emotion annotators.

Pick the version whose **emotional intensity matches the Chinese most exactly** —
neither stronger nor weaker. This outranks fluency: annotators rate feelings,
and a translation that reads better but feels angrier is worse than useless,
because the error lands directly in the data.

Reject a version if it:
- adds an intensifier, exclamation, or emotive idiom the Chinese lacks
- softens something blunt, or sharpens something mild
- completes a fragment, or resolves ambiguity toward the more dramatic reading
- is noticeably longer than the other while saying the same thing

Check for these words specifically. Each one is almost always an addition
the Chinese does not license: so, such, really, totally, absolutely, just,
even, ever, never, at all, damn, terrible, wonderful. 好变态哦 is
"that's perverted", not "that's SO perverted" — 哦 is a soft sentence-final
particle, not an intensifier.

**"It conveys the tone better" is a reason to REJECT a version, not to pick it.**
If one version reads as more forceful, more impatient, or more emotional than
the other, that is the version adding something. The annotator's job is to hear
the tone in the original; your job is not to say it for them. 别做梦了 is
dissuasion ("Don\'t dream"), not a rebuke ("Stop dreaming"); 没 is "not",
never "never".

Between two versions that are equally faithful, prefer the shorter, more
readable one: annotators who cannot parse the English will guess, and guesses
are noise too — but length matters as well, because the English scrolls
alongside the Chinese.

Answer with the choice and one short sentence saying what decided it."""

JUDGE_TEMPLATE = """Chinese: {text}

A. literal:   {literal}
B. idiomatic: {idiomatic}"""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "choice": {"type": "string", "enum": ["literal", "idiomatic"]},
        "reason": {"type": "string", "description": "一句话，说明什么决定了取舍"},
    },
    "required": ["choice", "reason"],
}


def sentence_text(sentence: dict) -> str:
    return "".join(token["text"] for token in sentence["tokens"])


def draft(gemini, source: str) -> dict:
    """第一遍：同时给出平淡版与地道版。"""
    text, _ = gemini.generate(
        [DRAFT_SYSTEM, DRAFT_TEMPLATE.format(text=source)],
        schema=DRAFT_SCHEMA,
    )
    got = json.loads(text)
    return {"literal": got["literal"].strip(),
            "idiomatic": got["idiomatic"].strip()}


def judge(gemini, source: str, candidates: dict) -> dict:
    """第二遍：选情感强度与原文最贴的那版，并记下理由。"""
    text, _ = gemini.generate(
        [JUDGE_SYSTEM, JUDGE_TEMPLATE.format(text=source, **candidates)],
        schema=JUDGE_SCHEMA,
    )
    got = json.loads(text)
    choice = got["choice"] if got["choice"] in candidates else "literal"
    return {"choice": choice, "reason": got.get("reason", "").strip()[:200]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条，用于试跑")
    ap.add_argument("--rpm", type=int, default=120)
    ap.add_argument("--redo", action="store_true", help="已有译文也重做")
    ap.add_argument("--print", action="store_true", help="逐句打印结果，便于人工过目")
    args = ap.parse_args()

    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("请先 export GEMINI_API_KEY")

    todo = []
    for path in sorted(TRANSCRIPTS.glob("chsims_*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if args.redo or any("text_en" not in s for s in record["sentences"]):
            todo.append((path, record))
    if args.limit:
        todo = todo[: args.limit]

    lines = sum(len(r["sentences"]) for _, r in todo)
    print(f"待译 {len(todo)} 条样本、{lines} 句；每句两次调用（起草 + 评审）",
          flush=True)
    if not todo:
        return 0

    gemini = Gemini(rpm=args.rpm)
    picks = {"literal": 0, "idiomatic": 0}
    done = 0
    for path, record in todo:
        for sentence in record["sentences"]:
            if "text_en" in sentence and not args.redo:
                continue
            source = sentence_text(sentence)
            if not source.strip():
                sentence["text_zh"] = source
                sentence["text_en"] = ""
                continue
            candidates = draft(gemini, source)
            verdict = judge(gemini, source, candidates)
            picks[verdict["choice"]] += 1
            sentence["text_zh"] = source
            sentence["text_en"] = candidates[verdict["choice"]]
            # 两个候选与评审理由都留着：抽查时看得见它为什么这么选，
            # 改主意时不必重译
            sentence["en_candidates"] = candidates
            sentence["en_choice"] = verdict["choice"]
            sentence["en_reason"] = verdict["reason"]
            if args.print:
                print(f"  {source}")
                print(f"    literal   : {candidates['literal']}")
                print(f"    idiomatic : {candidates['idiomatic']}")
                print(f"    → {verdict['choice']}：{verdict['reason']}", flush=True)
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        done += 1
        if done % 50 == 0:
            print(f"  {done}/{len(todo)}  {gemini.usage}", flush=True)

    total = picks["literal"] + picks["idiomatic"]
    if total:
        print(f"\n选用：平淡 {picks['literal']}（{picks['literal']/total:.0%}）、"
              f"地道 {picks['idiomatic']}（{picks['idiomatic']/total:.0%}）")
    print(f"完成 {done} 条。{gemini.usage}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
