"""把人工核对结果应用到 manifest。

人工判定优先于任何模型判据：选中的框直接重裁，废弃的移出交付集。
除了人工废弃的，再按「人脸 <50px 且画面多人」补一条规则——
这个门限是拿人工判定回校出来的：0-40px 档废弃率 75%，65-80px 档只有 13%，
单人画面即使脸小也能用（没有第二个人可混淆），多人画面脸太小就认不出是哪个。

产出：
  manifest.jsonl    只含交付用的有效样本
  discarded.jsonl   被剔除的样本与原因，供 05-annotation 从标注池排除
"""
import argparse, collections, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import FACESCAN, FRAMES, MANIFEST, OUT, crop_face, load_done
from pick_local import read_frames_at

DISCARDED = OUT / "discarded.jsonl"
TINY_FACE_PX = 50        # 多人画面里低于此高度的人脸认不出是谁


def is_multi(scan_rec):
    return (scan_rec.get("n_faces_max") or 1) > 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("picks", help="speaker_picks.json")
    ap.add_argument("--manifest", default=str(MANIFEST))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import cv2
    picks = json.loads(Path(args.picks).read_text(encoding="utf-8"))["results"]
    mani = load_done(args.manifest)
    scan = load_done(FACESCAN)

    # 规则补剔：多人画面里脸太小的，人工没看到也一并剔除
    rule_drop = {sid for sid, m in mani.items()
                 if m.get("bbox") and m["bbox"][3] < TINY_FACE_PX
                 and is_multi(scan.get(sid, {}))
                 and picks.get(sid, {}).get("action") != "pick"}

    tally = collections.Counter()
    discarded = []
    for sid, p in picks.items():
        m = mani.get(sid)
        if m is None:
            tally["not_in_manifest"] += 1
            continue
        act = p["action"]
        if act == "pick":
            frames = read_frames_at(scan[sid]["video_path"], [p["frame_idx"]])
            frame = frames.get(p["frame_idx"])
            if frame is None:
                m["status"] = "needs_review"
                m["note"] = "人工已选定，但该帧重新解码失败"
                tally["recrop_failed"] += 1
                continue
            if not args.dry_run:
                img = crop_face(frame, p["bbox"])
                cv2.imwrite(str(FRAMES / f"{sid}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
            m.update(frame_path=f"frames/{sid}.jpg", source_time=p["t"],
                     bbox=[round(v, 1) for v in p["bbox"]],
                     method="human", confidence=1.0, status="ok",
                     note="人工核对确认")
            tally["pick"] += 1
        elif act == "discard":
            m["status"] = "discarded"
            m["note"] = "人工判定：视频质量不可用"
            discarded.append({**m, "drop_reason": "human_discard"})
            tally["discard"] += 1
        elif act == "no_speaker":
            m["status"] = "needs_review"
            m["note"] = "人工判定：候选人脸里没有说话人，待全片重搜"
            tally["no_speaker"] += 1
        elif act == "skip":
            tally["skip"] += 1

    for sid in rule_drop:
        m = mani[sid]
        if m["status"] == "discarded":
            continue
        m["status"] = "discarded"
        m["note"] = f"规则判定：多人画面且人脸仅 {m['bbox'][3]:.0f}px，认不出是谁"
        discarded.append({**m, "drop_reason": "tiny_face_multi_person"})
        tally["rule_discard"] += 1

    keep = [m for m in mani.values() if m["status"] != "discarded"]
    print("应用结果:", dict(tally))
    print(f"交付集 {len(keep)} 条，剔除 {len(discarded)} 条")
    print("剔除按来源:", dict(collections.Counter(d["source"] for d in discarded)))
    print("剔除按原因:", dict(collections.Counter(d["drop_reason"] for d in discarded)))
    print("交付集状态:", dict(collections.Counter(m["status"] for m in keep)))
    if args.dry_run:
        return

    path = Path(args.manifest)
    path.replace(path.with_suffix(".jsonl.prepick"))
    with open(path, "w", encoding="utf-8") as f:
        for m in keep:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    with open(DISCARDED, "w", encoding="utf-8") as f:
        for d in discarded:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    (OUT / "discarded.txt").write_text(
        "\n".join(sorted(d["sample_id"] for d in discarded)) + "\n", encoding="utf-8")
    print(f"\n写回 {path}（上一版 {path.name}.prepick）")
    print(f"剔除清单 {DISCARDED} 与 {OUT/'discarded.txt'}")


if __name__ == "__main__":
    main()
