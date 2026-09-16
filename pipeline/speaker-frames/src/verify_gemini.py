"""Gemini 复核层：对已产出的静帧做第二次独立确认。

人脸库匹配（facelib）和 Gemini 是两条互不依赖的判据——
前者比对角色原型的几何特征，后者靠模型对角色的先验认知。
两者都说是同一个人，这张图基本可以放心；意见不一致的，才值得人去看。
这样把人工核对的负担从「逐条审查」压到「只看两个模型吵架的那些」。

只读 manifest、只写 verify.jsonl，不改动已产出的图与 manifest。
"""
import argparse, collections, json, sys, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import FACESCAN, MANIFEST, OUT, JsonlWriter, ensure_dirs, load_done

VERIFY = OUT / "verify.jsonl"

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["yes", "no", "unsure"],
                    "description": "这张脸是不是指定的那个人"},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "confidence", "reason"],
}

PROMPT_ASD = """第一个输入是一段 {dur} 秒的中文影视片段，其中有人说了这句台词：「{text}」
第二个输入是我们从这段视频里截出的一张人脸。

请判断：**说这句台词的人，就是这张截图里的人吗？**

判断依据按可靠性排序：唇部运动与语音同步 > 台词语气与表情的匹配 > 镜头语言。

- 确认就是同一个人，verdict 填 yes
- 说话的是画面里另一个人、或说话人根本没出现在这张截图里，填 no
- 看不清唇动、无法判断时填 unsure，不要硬猜
- confidence 反映把握程度"""

PROMPT = """这是电视剧《{show}》里的一张人物面部截图。

请判断：**画面里这个人是 {name} 吗？**

- 确认是本人，verdict 填 yes
- 确认是别的角色，verdict 填 no
- 画面太糊/侧脸太多/看不清，无法判断时填 unsure，不要硬猜
- confidence 反映把握程度"""

SHOW_BY_SOURCE = {"meld": "Friends"}
# mustard 横跨 BBT / Friends / Golden Girls / Sarcasmos 多部剧，剧名只在 facescan 的
# extra 里（manifest 按输出契约不带 extra），取错了会让模型拿着错剧名去认人
SHOW_CODE = {"BBT": "The Big Bang Theory", "FRIENDS": "Friends",
             "GOLDENGIRLS": "The Golden Girls", "SARCASMOHOLICS": "Sarcasmoholics"}


def show_of(rec, extra):
    code = str((extra or {}).get("show") or "").strip().upper()
    return SHOW_CODE.get(code) or (code.title() if code else None) \
        or SHOW_BY_SOURCE.get(rec["source"]) or "这部剧"


def build_parts(rec, extra, mode):
    """name 模式只送裁切图；asd 模式送视频 + 裁切图。

    复核必须换一种问法才有意义：判别阶段问的是「从编号框里选一个」，
    那是多选一，模型会硬选；复核阶段问「是不是这个人」，是二元验证，
    答不上来可以说 no/unsure。meld 上正是这个差异抓出了 90 条自我矛盾。
    """
    from google.genai import types
    img = types.Part.from_bytes(data=(OUT / rec["frame_path"]).read_bytes(),
                                mime_type="image/jpeg")
    if mode == "name":
        return [PROMPT.format(show=show_of(rec, extra), name=rec.get("speaker_name")), img]

    vid = types.Part(
        inline_data=types.Blob(data=Path(rec["_video_path"]).read_bytes(),
                               mime_type="video/mp4"),
        video_metadata=types.VideoMetadata(fps=3.0),
    )
    prompt = PROMPT_ASD.format(dur=rec.get("_duration") or "?",
                               text=(extra or {}).get("text") or "")
    return [prompt, vid, img]


def verify_one(rec, gem, extra=None, mode="name"):
    sid = rec["sample_id"]
    out = {"sample_id": sid, "source": rec["source"],
           "speaker_name": rec.get("speaker_name"),
           "method": rec.get("method"), "match_confidence": rec.get("confidence"),
           "verdict": "error", "verify_confidence": 0.0, "reason": ""}
    try:
        text, _ = gem.generate(build_parts(rec, extra, mode), schema=SCHEMA)
        ans = json.loads(text)
        out.update(verdict=str(ans.get("verdict", "error")),
                   verify_confidence=round(float(ans.get("confidence", 0)), 4),
                   reason=str(ans.get("reason", ""))[:160])
    except Exception as exc:
        out["reason"] = f"{type(exc).__name__}: {exc}"[:200]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="meld,mustard")
    ap.add_argument("--mode", default="", help="name / asd；默认按来源推断")
    ap.add_argument("--manifest", default=str(MANIFEST))
    ap.add_argument("--out", default=str(VERIFY))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--rpm", type=int, default=120)
    args = ap.parse_args()

    ensure_dirs()
    sources = args.sources.split(",")
    done = load_done(args.out)
    scan = load_done(FACESCAN)
    recs = [r for r in load_done(args.manifest).values()
            if r["source"] in sources and r.get("frame_path")
            and (r.get("speaker_name") or args.mode == "asd" or sources == ["chsims"])
            and r["sample_id"] not in done]
    recs.sort(key=lambda r: r["sample_id"])
    if args.limit:
        recs = recs[:args.limit]
    mode = args.mode or ("asd" if sources == ["chsims"] else "name")
    if mode == "asd":            # asd 复核要原视频，从 facescan 带进来
        for r in recs:
            sc = scan.get(r["sample_id"]) or {}
            r["_video_path"] = sc.get("video_path")
            r["_duration"] = sc.get("duration")
        recs = [r for r in recs if r.get("_video_path")]
    print(f"待复核 {len(recs)} 条（已复核 {len(done)}），{mode} 模式", flush=True)
    if not recs:
        return

    from gemini_client import Gemini
    gem = Gemini(rpm=args.rpm)
    lock = threading.Lock()
    tally = collections.Counter()
    with JsonlWriter(args.out) as w:
        def run(rec):
            out = verify_one(rec, gem, (scan.get(rec["sample_id"]) or {}).get("extra"), mode)
            with lock:
                w.write(out)
                tally[out["verdict"]] += 1
                n = sum(tally.values())
                if n % 50 == 0 or n == len(recs):
                    print(f"  {n}/{len(recs)} {dict(tally)} | {gem.usage.summary()}", flush=True)
        with ThreadPoolExecutor(args.concurrency) as ex:
            list(ex.map(run, recs))
    print(f"完成：{dict(tally)} | {gem.usage.summary()}")
    print(f"\n其中 verdict=no 的是两个判据打架的条目，最该人工看：")
    for r in load_done(args.out).values():
        if r["verdict"] == "no":
            print(f"  {r['sample_id']:24} 标称={r['speaker_name']:14} "
                  f"库相似度={r['match_confidence']} | {r['reason'][:60]}")


if __name__ == "__main__":
    main()
