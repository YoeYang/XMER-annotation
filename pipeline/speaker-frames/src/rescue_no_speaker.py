"""救回「候选里没有说话人」的样本：全片密集重扫。

人工判定这些样本的说话人不在候选里，原因是原来只扫了 9 帧——
说话人可能在别的时刻才转过脸来。这里把采样密度提到每 0.25 秒一帧全片重扫，
跨帧聚类出人物，再和原候选比对，看是否冒出了新的人。

冒出新人的交给下一轮人工确认；整段都没有新人的，说明说话人确实全程没露脸
（画外音、只有背影），只能剔除。
"""
import argparse, collections, json, os, sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (FACESCAN, MANIFEST, OUT, YUNET, crop_face, faces_for_pick,
                    face_score, load_done, sharpness)
from facelib import SAME_COSINE, embed

DENSE_STEP_SEC = 0.25
MAX_DENSE_FRAMES = 60
OUTDIR = OUT / "rescue"

_det = None


def detector():
    global _det
    if _det is None:
        import cv2
        _det = cv2.FaceDetectorYN.create(str(YUNET), "", (320, 320), 0.6, 0.3, 5000)
    return _det


def dense_scan(video_path):
    """全片密集采样，返回 [(t, frame, faces)]。"""
    import cv2
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    n = 0
    while cap.grab():
        n += 1
    cap.release()
    if n <= 0:
        return []
    step = max(1, int(round(fps * DENSE_STEP_SEC)))
    targets = list(range(0, n, step))[:MAX_DENSE_FRAMES]
    want = set(targets)

    cap = cv2.VideoCapture(str(video_path))
    det = detector()
    out = []
    for i in range(targets[-1] + 1):
        if i not in want:
            if not cap.grab():
                break
            continue
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        det.setInputSize((frame.shape[1], frame.shape[0]))
        _, faces = det.detect(frame)
        faces = [] if faces is None else faces
        rows = [{"bbox": [round(float(v), 1) for v in f[:4]],
                 "kps": [round(float(v), 1) for v in f[4:14]],
                 "det": round(float(f[14]), 4),
                 "score": round(face_score(f, frame.shape[1], frame.shape[0]), 4)}
                for f in faces]
        out.append((round(i / fps, 3), frame, rows, round(sharpness(frame), 1)))
    cap.release()
    return out


def process(task):
    sid, rec, old_boxes = task
    try:
        frames = dense_scan(rec["video_path"])
        if not frames:
            return {"sample_id": sid, "error": "decode_failed"}
        items = []
        for t, frame, rows, sharp in frames:
            for face in faces_for_pick(rows, rec["h"])[0]:
                try:
                    items.append((t, face, embed(frame, face), sharp, frame))
                except Exception:
                    continue
        if not items:
            return {"sample_id": sid, "n_dense": len(frames), "people": [], "new": 0}

        feats = np.stack([it[2] for it in items])
        adj = (feats @ feats.T) >= SAME_COSINE
        seen = np.zeros(len(items), bool)
        people = []
        for i in range(len(items)):
            if seen[i]:
                continue
            stack, comp = [i], []
            seen[i] = True
            while stack:
                u = stack.pop()
                comp.append(u)
                for v in np.nonzero(adj[u] & ~seen)[0]:
                    seen[v] = True
                    stack.append(int(v))
            people.append(comp)

        # 和原来 9 帧里出现过的人比：特征相似就是同一个人，算不上新发现
        old_feats = [f for f in old_boxes if f is not None]
        res = []
        for comp in people:
            best = max(comp, key=lambda j: items[j][1]["score"]
                       * (0.7 + 0.3 * min(1.0, items[j][3] / max(1.0, max(x[3] for x in frames)))))
            t, face, feat, _, frame = items[best]
            is_new = all(float(feat @ of) < SAME_COSINE for of in old_feats) if old_feats else True
            res.append({"t": t, "bbox": face["bbox"], "seen": len(comp),
                        "is_new": bool(is_new), "_frame_t": t})
            if is_new:
                import cv2
                OUTDIR.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(OUTDIR / f"{sid}__new{len(res)}.jpg"),
                            crop_face(frame, face["bbox"], size=300),
                            [cv2.IMWRITE_JPEG_QUALITY, 88])
        return {"sample_id": sid, "n_dense": len(frames),
                "people": res, "new": sum(1 for r in res if r["is_new"])}
    except Exception as exc:
        return {"sample_id": sid, "error": f"{type(exc).__name__}: {exc}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    import cv2
    mani = load_done(MANIFEST)
    scan = load_done(FACESCAN)
    targets = [s for s, m in mani.items()
               if m["status"] == "needs_review" and "没有说话人" in (m.get("note") or "")]
    print(f"待重搜 {len(targets)} 条，密集采样每 {DENSE_STEP_SEC}s 一帧", flush=True)

    # 原来 9 帧里出现过哪些人：用特征比对，避免把同一个人当成新发现
    tasks = []
    for sid in targets:
        rec = scan[sid]
        old = []
        from pick_local import read_frames_at
        fr = read_frames_at(rec["video_path"], [f["idx"] for f in rec["frames"]])
        for f in rec["frames"]:
            frame = fr.get(f["idx"])
            if frame is None:
                continue
            for face in faces_for_pick(f["faces"], rec["h"])[0]:
                try:
                    old.append(embed(frame, face))
                except Exception:
                    pass
        tasks.append((sid, rec, old))

    results = []
    with Pool(args.workers) as pool:
        for n, r in enumerate(pool.imap_unordered(process, tasks), 1):
            results.append(r)
            msg = (f"错误 {r['error']}" if r.get("error")
                   else f"扫 {r['n_dense']} 帧，识别 {len(r['people'])} 人，新发现 {r['new']} 人")
            print(f"  {n}/{len(tasks)} {r['sample_id']}: {msg}", flush=True)
    (OUT / "rescue.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    tot_new = sum(r.get("new", 0) for r in results)
    has_new = sum(1 for r in results if r.get("new"))
    print(f"\n{has_new}/{len(results)} 条找到了原先没扫到的人，共 {tot_new} 个新候选")
    print(f"新候选裁切图 -> {OUTDIR}，明细 -> {OUT/'rescue.json'}")


if __name__ == "__main__":
    main()
