"""meld / mustard：用角色原型库在全部扫描帧里搜目标人物。

不再分单人桶 / 多人桶——单人桶的「反应镜头」（画面是听话人特写、说话人在画外）
和多人桶的「选错人」是同一类错误，都要靠「这张脸是不是标称的那个角色」来判。
拿原型搜全部 9 帧的所有候选脸，说话人第 7 帧才露脸就用第 7 帧。

匹配不上的（零库存配角、全帧都对不上）留给 pick_gemini 兜底。
"""
import argparse, collections, json, os, sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (OUT, FACESCAN, FRAMES, MANIFEST, JsonlWriter, crop_face, ensure_dirs,
                    faces_for_pick, load_done)
from facelib import embed
from pick_local import read_frames_at

GALLERY = OUT / "gallery.npz"

# 门限先由 out/embeds.npz 上的留一法标定（同人均值 0.710 / 异人均值 0.154），
# 再用全量 1182 条的 Gemini 复核结果回校——按相似度分层的「判非本人」率实测为：
#   0.28-0.40 → 41.2%   0.40-0.50 → 30.0%   0.50-0.60 → 10.7%
#   0.60-0.70 →  2.7%   0.70 以上 →  3.0%
# 可见 0.40 定得太松，0.55 以上才真正稳定，故 ACCEPT 上调到 0.55。
# 注意：跑了 verify_gemini + merge_verify 时，最终 status 以复核结论为准，
# 这两个门限只决定「没有复核时」的产出可信度。
ACCEPT = 0.55
SUSPECT = 0.28

_gal = None


def gallery():
    """{归一化角色名: 原型向量}。大小写归一是因为 meld 的 Chandler 与 mustard 的
    CHANDLER 是同一个演员。"""
    global _gal
    if _gal is None:
        d = np.load(GALLERY, allow_pickle=False)
        _gal = {str(n).strip().lower(): p for n, p in zip(d["names"], d["protos"])}
    return _gal


def norm_name(name):
    return str(name or "").strip().lower()


def match_one(rec):
    """在全部扫描帧里找与标称角色最像的一张脸。"""
    import cv2
    sid = rec["sample_id"]
    out = {"sample_id": sid, "source": rec["source"],
           "speaker_name": rec.get("speaker_name"),
           "frame_path": None, "source_time": None, "bbox": None,
           "method": "facelib", "confidence": 0.0, "status": "failed", "note": ""}

    proto = gallery().get(norm_name(rec.get("speaker_name")))
    if proto is None:
        out.update(status="deferred", note="no_gallery_entry")   # 交给 Gemini 兜底
        return out
    if rec.get("error"):
        out["note"] = rec["error"]
        return out

    cand = [(fr, f) for fr in rec["frames"]
            for f in faces_for_pick(fr["faces"], rec["h"])[0]]
    if not cand:
        out.update(status="deferred", note="no_candidate_face")
        return out

    frames = read_frames_at(rec["video_path"], [fr["idx"] for fr, _ in cand])
    best = None
    for fr, face in cand:
        frame = frames.get(fr["idx"])
        if frame is None:
            continue
        try:
            sim = float(embed(frame, face) @ proto)
        except Exception:
            continue
        # 同分时偏向更清晰、更正脸的那张，辨识度优先
        key = (round(sim, 3), face["score"])
        if best is None or key > best[0]:
            best = (key, sim, fr, face, frame)
    if best is None:
        out.update(status="deferred", note="embed_failed")
        return out

    _, sim, fr, face, frame = best
    out.update(confidence=round(sim, 4), source_time=fr["t"],
               bbox=[round(v, 1) for v in face["bbox"]])
    if sim < SUSPECT:
        # 全部帧都不像标称角色：多半说话人整段不在画面，交给 Gemini
        out.update(status="deferred", note=f"best_sim={sim:.3f}<{SUSPECT}")
        return out

    img = crop_face(frame, face["bbox"])
    cv2.imwrite(str(FRAMES / f"{sid}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    out.update(frame_path=f"frames/{sid}.jpg",
               status="ok" if sim >= ACCEPT else "needs_review",
               note="" if sim >= ACCEPT else f"low_sim={sim:.3f}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="meld,mustard")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=str(MANIFEST))
    args = ap.parse_args()

    ensure_dirs()
    sources = args.sources.split(",")
    done = load_done(args.out)
    recs = [r for r in load_done(FACESCAN).values()
            if r["source"] in sources and r["sample_id"] not in done]
    recs.sort(key=lambda r: r["sample_id"])
    if args.limit:
        recs = recs[:args.limit]
    print(f"待匹配 {len(recs)} 条，原型库 {len(gallery())} 个角色", flush=True)
    if not recs:
        return

    tally = collections.Counter()
    with JsonlWriter(args.out) as w, Pool(args.workers) as pool:
        for n, out in enumerate(pool.imap_unordered(match_one, recs, chunksize=4), 1):
            w.write(out)
            tally[out["status"]] += 1
            if n % 100 == 0 or n == len(recs):
                print(f"  {n}/{len(recs)}  {dict(tally)}", flush=True)
    print(f"完成：{dict(tally)}")
    print(f"其中 deferred {tally['deferred']} 条交给 pick_gemini 兜底")


if __name__ == "__main__":
    main()
