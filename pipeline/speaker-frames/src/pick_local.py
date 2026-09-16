"""阶段 1：单人桶本地选帧。

对 facescan 判为 single 的样本，在扫描过的帧里挑"最好认"的一帧——
人脸大、居中、正脸、画面锐利——裁切后写 frames/ 与 manifest.jsonl。
零 API 成本，可断点续跑。
"""
import argparse, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (FACESCAN, FRAMES, MANIFEST, CROP_SIZE, JsonlWriter, crop_face,
                    ensure_dirs, faces_for_pick, load_done, main_faces)

# 低于此分认为不够好认，标 needs_review 让人优先看
LOW_CONF = 0.35
# 全程只有一张候选脸时（iemocap 的单人半身机位、mosi 的独白特写）用更低的门限：
# 画面里没有第二个人可选，"脸小"不是可纠正的错误，标出来只会稀释核对页的信噪比，
# 只有低到疑似误检才值得人看一眼
SINGLE_LOW_CONF = 0.15


def pick_best_frame(rec):
    """返回 (frame_entry, face, conf)；挑不出时返回 (None, None, 0)。"""
    sharps = [f["sharp"] for f in rec["frames"]] or [1.0]
    smax = max(sharps) or 1.0
    best = (None, None, -1.0)
    for fr in rec["frames"]:
        cand = main_faces(fr["faces"], rec["h"])
        if len(cand) != 1:
            continue
        face = cand[0]
        # 清晰度只作乘性修正，避免为了锐利而牺牲人脸大小/正脸
        q = face["score"] * (0.7 + 0.3 * min(1.0, fr["sharp"] / smax))
        if q > best[2]:
            best = (fr, face, q)
    if best[0] is None:                      # 退而求其次：取分最高的脸，哪怕那帧有多张
        for fr in rec["frames"]:
            cand, loose = faces_for_pick(fr["faces"], rec["h"])
            for face in cand:
                q = face["score"] * (0.5 if loose else 0.8)
                if q > best[2]:
                    best = (fr, face, q)
    return best


def read_frames_at(video_path, idxs):
    """顺序解码一次，取出多个指定帧，返回 {idx: frame}。

    不能用 cap.set(POS_FRAMES)——这批素材上按帧号定位大量失败。
    一次解码取多帧，比对每帧各解码一遍省一个数量级。
    """
    import cv2
    want = sorted(set(idxs))
    if not want:
        return {}
    cap = cv2.VideoCapture(str(video_path))
    got, wset = {}, set(want)
    for i in range(want[-1] + 1):
        if i in wset:
            ok, f = cap.read()
            if not ok or f is None:
                break
            got[i] = f
        elif not cap.grab():
            break
    cap.release()
    return got


def read_frame_at(video_path, idx):
    return read_frames_at(video_path, [idx]).get(idx)


def process(rec):
    import cv2
    sid = rec["sample_id"]
    out = {"sample_id": sid, "source": rec["source"],
           "speaker_name": rec.get("speaker_name"),
           "frame_path": None, "source_time": None, "bbox": None,
           "method": "largest-face", "confidence": 0.0,
           "status": "failed", "note": ""}

    if rec.get("error"):
        out["note"] = rec["error"]
        return out
    fr, face, conf = pick_best_frame(rec)
    if fr is None:
        out["note"] = "no_face_detected"
        return out

    frame = read_frame_at(rec["video_path"], fr["idx"])
    if frame is None:
        out["note"] = "decode_failed"
        return out

    img = crop_face(frame, face["bbox"])
    path = FRAMES / f"{sid}.jpg"
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    floor = SINGLE_LOW_CONF if rec.get("n_faces_max", 9) <= 1 else LOW_CONF
    out.update(frame_path=f"frames/{sid}.jpg", source_time=fr["t"],
               bbox=[round(v, 1) for v in face["bbox"]],
               confidence=round(min(1.0, conf), 4),
               status="ok" if conf >= floor else "needs_review",
               note="" if conf >= floor else "low_face_quality")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--source", default="")
    ap.add_argument("--bucket", default="single", help="single / none / all")
    ap.add_argument("--out", default=str(MANIFEST), help="manifest 路径（调试时可另指）")
    args = ap.parse_args()

    ensure_dirs()
    done = load_done(args.out)
    scans = [r for r in load_done(FACESCAN).values()
             if (args.bucket == "all" or r.get("bucket") == args.bucket)
             and r["sample_id"] not in done
             and (not args.source or r["source"] == args.source)]
    scans.sort(key=lambda r: r["sample_id"])
    if args.limit:
        scans = scans[:args.limit]
    print(f"待处理 {len(scans)} 条（manifest 已有 {len(done)}）", flush=True)

    ok = rev = fail = 0
    with JsonlWriter(args.out) as w:
        for n, rec in enumerate(scans, 1):
            out = process(rec)
            w.write(out)
            ok += out["status"] == "ok"
            rev += out["status"] == "needs_review"
            fail += out["status"] == "failed"
            if n % 200 == 0 or n == len(scans):
                print(f"  {n}/{len(scans)}  ok={ok} needs_review={rev} failed={fail}", flush=True)
    print(f"完成：ok={ok} needs_review={rev} failed={fail}")


if __name__ == "__main__":
    main()
