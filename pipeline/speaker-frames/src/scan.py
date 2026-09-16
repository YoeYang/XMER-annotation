"""阶段 0：全量本地人脸扫描，产出 out/facescan.jsonl。

每条视频等距抽 SCAN_FRAMES 帧做 YuNet 检测，记录每帧的人脸框、关键点、清晰度，
并按人脸数中位数分桶：single（直接本地选帧）/ multi（需要说话人判别）/ none（失败）。
纯 CPU，可断点续跑。
"""
import argparse, json, os, sys, time
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from common import (FACESCAN, SCAN_FRAMES, YUNET, JsonlWriter, count_main, ensure_dirs,
                    face_score, load_done, sharpness)
from resolve import load_pool, resolve

_det = None


def _detector():
    global _det
    if _det is None:
        import cv2
        _det = cv2.FaceDetectorYN.create(str(YUNET), "", (320, 320), 0.6, 0.3, 5000)
    return _det


def scan_one(task):
    sample_id, source = task
    import cv2
    rec = {"sample_id": sample_id, "source": source}
    try:
        r = resolve(sample_id, source)
        if r is None or not r["video_path"].exists():
            rec.update(bucket="none", error="video_missing")
            return rec
        rec["video_path"] = str(r["video_path"])
        rec["speaker_name"] = r["speaker_name"]
        rec["gender"] = r["gender"]
        rec["extra"] = r["extra"]

        # 容器元数据常虚报帧数（iemocap 声称 266 帧实际只有 52 帧可解码），
        # 故先用 grab() 数出真实可解码帧数，再据此定位采样点。
        cap = cv2.VideoCapture(str(r["video_path"]))
        W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        n_real = 0
        while cap.grab():
            n_real += 1
        cap.release()
        if n_real <= 0 or W <= 0 or H <= 0:
            rec.update(bucket="none", error="unreadable")
            return rec
        rec.update(w=W, h=H, fps=round(fps, 3), n_total=n_real,
                   duration=round(n_real / fps, 3) if fps else None)

        det = _detector()
        det.setInputSize((W, H))
        # 掐掉首尾 6%，剪辑边界常有转场/黑帧
        targets = sorted({min(n_real - 1, int(n_real * (0.06 + 0.88 * (i + 0.5) / SCAN_FRAMES)))
                          for i in range(SCAN_FRAMES)})
        want = set(targets)
        frames, counts = [], []
        cap = cv2.VideoCapture(str(r["video_path"]))
        for idx in range(targets[-1] + 1):
            if idx not in want:
                if not cap.grab():
                    break
                continue
            t_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            _, faces = det.detect(frame)
            faces = [] if faces is None else faces
            entry = {"idx": idx, "t": round(t_ms / 1000, 3),
                     "sharp": round(sharpness(frame), 1), "faces": []}
            for f in faces:
                entry["faces"].append({
                    "bbox": [round(float(v), 1) for v in f[:4]],
                    "kps": [round(float(v), 1) for v in f[4:14]],
                    "det": round(float(f[14]), 4),
                    "score": round(face_score(f, W, H), 4),
                })
            entry["n_main"] = count_main(entry["faces"], H)
            frames.append(entry)
            counts.append(entry["n_main"])
        cap.release()

        if not frames:
            rec.update(bucket="none", error="no_frame_decoded")
            return rec
        med = int(np.median(counts))
        rec["n_faces_per_frame"] = counts
        rec["n_faces_median"] = med
        rec["n_faces_max"] = int(max(counts))
        rec["frames"] = frames
        rec["bucket"] = "none" if med == 0 and max(counts) == 0 else ("single" if med <= 1 else "multi")
        rec["error"] = None
    except Exception as exc:                      # 单条失败不能卡住整批
        rec.update(bucket="none", error=f"{type(exc).__name__}: {exc}")
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--limit", type=int, default=0, help="只扫前 N 条（冒烟用）")
    ap.add_argument("--source", default="", help="只扫某个来源")
    args = ap.parse_args()

    ensure_dirs()
    done = load_done(FACESCAN)
    tasks = [(s, src) for s, src in load_pool()
             if s not in done and (not args.source or src == args.source)]
    if args.limit:
        tasks = tasks[:args.limit]
    print(f"待扫 {len(tasks)} 条（已完成 {len(done)}），workers={args.workers}", flush=True)
    if not tasks:
        return

    t0 = time.time()
    with JsonlWriter(FACESCAN) as w, Pool(args.workers) as pool:
        for n, rec in enumerate(pool.imap_unordered(scan_one, tasks, chunksize=4), 1):
            w.write(rec)
            if n % 200 == 0 or n == len(tasks):
                el = time.time() - t0
                print(f"  {n}/{len(tasks)}  {el:.0f}s  eta {el/n*(len(tasks)-n):.0f}s", flush=True)
    print(f"完成，用时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
