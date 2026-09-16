"""把 Gemini 复核结论并回 manifest。

对 method=facelib 的条目，这是两条真正独立的判据：人脸库比对的是角色原型的
几何特征，Gemini 靠的是对角色的先验认知，两边都认同才算确认。

对 method=gemini 的条目，复核问的是同一个模型，不构成独立判据，但仍抓得住
过度自信——判别阶段「从编号框里选一个」会硬选，复核阶段「这是不是 X」则会否定。
实测配角上这种自我矛盾并不少见。

只要有一边不认就降级 needs_review 交人工：静帧指错人的代价是该样本
四个模态的标注一起作废，宁可多看几张也不能放过。

只改 status / note / method，不动图与 bbox。
"""
import argparse, collections, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import MANIFEST, OUT, load_done

VERIFY = OUT / "verify.jsonl"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(MANIFEST))
    ap.add_argument("--verify", default=str(VERIFY))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    mani = load_done(args.manifest)
    ver = load_done(args.verify)
    tally = collections.Counter()

    for sid, v in ver.items():
        rec = mani.get(sid)
        if rec is None:
            continue
        verdict = v.get("verdict")
        reason = (v.get("reason") or "")[:120]
        # 判别阶段的原话要留住：两次说法都在，人工核对时才能看出模型在哪一步动摇了。
        # 只在第一次合并时保存，重复合并不会被复核结论污染。
        if "pick_note" not in rec:
            rec["pick_note"] = rec.get("note") or ""
        rec["verify_note"] = reason
        rec["verify"] = verdict
        rec["verify_confidence"] = v.get("verify_confidence")
        if verdict == "yes":
            # 两条判据一致，这张图可以放心。method 后缀只加一次，保证重复合并幂等
            if rec["status"] == "ok" and not str(rec["method"]).endswith("+gemini"):
                rec["method"] = f"{rec['method']}+gemini"
            tally[f"{rec['status']}/yes"] += 1
        elif verdict == "no":
            rec["status"] = "needs_review"
            if str(rec.get("method", "")).startswith("facelib"):
                rec["note"] = (f"判据冲突：人脸库相似度 {rec.get('confidence')} 认为是本人，"
                               f"Gemini 判非本人（{reason}）")
                tally["conflict/facelib_vs_gemini"] += 1
            else:
                rec["note"] = (f"Gemini 复核否定了自己先前的判别"
                               f"（判别自信度 {rec.get('confidence')}）：{reason}")
                tally["gemini_self_contradiction"] += 1
        elif verdict == "unsure":
            if rec["status"] == "ok":
                rec["status"] = "needs_review"
                rec["note"] = f"Gemini 无法确认（{reason}）"
            tally["unsure"] += 1
        else:
            tally["verify_error"] += 1

    print("合并结果:", dict(tally))
    if args.dry_run:
        return
    path = Path(args.manifest)
    path.replace(path.with_suffix(".jsonl.prev"))
    with open(path, "w", encoding="utf-8") as f:
        for rec in mani.values():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"已写回 {path}（上一版存为 {path.name}.prev）")
    print("最终状态:", dict(collections.Counter(r["status"] for r in mani.values())))


if __name__ == "__main__":
    main()
