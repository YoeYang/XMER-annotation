"""生成「看视频选说话人」的人工核对包。

核对者要做的判断只有一个：这段视频里说话的是谁。所以页面上只给两样东西——
视频本身，和画面里所有候选人脸。点一个人脸就是选定，另有一个「废弃」用于视频本身没法用的样本。

候选人脸要跨帧聚类：同一个人在 9 个扫描帧里出现多次，不能当成 9 个候选。
用 SFace 特征按同人阈值连通聚类，每个人只出一张最清晰的正脸做代表。
"""
import argparse, collections, json, os, shutil, subprocess, sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import FACESCAN, MANIFEST, OUT, crop_face, faces_for_pick, load_done
from facelib import SAME_COSINE, embed
from pick_local import read_frames_at

PACK = OUT / "pick_task"
VID_H = 360           # 转码高度，兼顾看得清和体积
VID_CRF = 30
FACE_PX = 150
MAX_CAND = 6


def cluster_faces(rec, frames):
    """返回候选人物列表，每项 (代表帧, 代表脸, 出现帧数)。"""
    items = []
    for fr in rec["frames"]:
        frame = frames.get(fr["idx"])
        if frame is None:
            continue
        for face in faces_for_pick(fr["faces"], rec["h"])[0]:
            try:
                items.append((fr, face, embed(frame, face)))
            except Exception:
                continue
    if not items:
        return []

    feats = np.stack([it[2] for it in items])
    n = len(items)
    adj = (feats @ feats.T) >= SAME_COSINE
    seen = np.zeros(n, bool)
    clusters = []
    for i in range(n):
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
        clusters.append(comp)

    smax = max((f["sharp"] for f in rec["frames"]), default=1.0) or 1.0
    out = []
    for comp in clusters:
        best = max(comp, key=lambda j: items[j][1]["score"]
                   * (0.7 + 0.3 * min(1.0, items[j][0]["sharp"] / smax)))
        fr, face, _ = items[best]
        out.append((fr, face, len(comp)))
    # 出现帧数多的排前面：更可能是这场戏的主角，也更可能是说话人
    out.sort(key=lambda x: (-x[2], x[0]["idx"]))
    return out[:MAX_CAND]


def transcode(src, dst, height=VID_H, crf=VID_CRF):
    """转小尺寸 mp4，保留音轨——有声音判断谁在说话准得多。

    -ac 2 是必须的：MELD 有一批 5.1 声道素材，aac 编码器不接受 6 声道会直接失败。
    """
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
           "-vf", f"scale=-2:{height}", "-c:v", "libx264", "-crf", str(crf),
           "-preset", "veryfast", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "64k", "-ac", "2",
           "-movflags", "+faststart", str(dst)]
    r = subprocess.run(cmd, capture_output=True)
    return dst.exists() and dst.stat().st_size > 0, r.stderr.decode()[:200]


def process(task):
    import cv2
    sid, rec, cur_bbox = task
    try:
        vdir, fdir = PACK / "videos", PACK / "faces"
        frames = read_frames_at(rec["video_path"], [f["idx"] for f in rec["frames"]])
        cands = cluster_faces(rec, frames)
        if not cands:
            return {"sample_id": sid, "error": "no_candidate"}

        entry = {"sample_id": sid, "source": rec["source"],
                 "speaker_name": rec.get("speaker_name"),
                 "text": (rec.get("extra") or {}).get("text") or "",
                 "duration": rec.get("duration"), "candidates": []}
        for i, (fr, face, seen) in enumerate(cands, 1):
            img = crop_face(frames[fr["idx"]], face["bbox"], size=FACE_PX * 2)
            img = cv2.resize(img, (FACE_PX, FACE_PX), interpolation=cv2.INTER_AREA)
            name = f"{sid}__{i}.jpg"
            cv2.imwrite(str(fdir / name), img, [cv2.IMWRITE_JPEG_QUALITY, 84])
            entry["candidates"].append({
                "id": i, "file": f"faces/{name}",
                "bbox": [round(v, 1) for v in face["bbox"]],
                "frame_idx": fr["idx"], "t": fr["t"], "seen": seen,
                # 标出流水线当前选的是哪个，核对者可以直接确认或改掉
                "current": bool(cur_bbox and abs(face["bbox"][0] - cur_bbox[0]) < 3
                                and abs(face["bbox"][1] - cur_bbox[1]) < 3),
            })
        ok, err = transcode(rec["video_path"], vdir / f"{sid}.mp4")
        if not ok:
            return {"sample_id": sid, "error": f"transcode_failed: {err}"}
        entry["video"] = f"videos/{sid}.mp4"
        return entry
    except Exception as exc:
        return {"sample_id": sid, "error": f"{type(exc).__name__}: {exc}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", default="needs_review", help="给哪些条目做；all 为全部")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    args = ap.parse_args()

    for d in (PACK, PACK / "videos", PACK / "faces"):
        d.mkdir(parents=True, exist_ok=True)
    mani = load_done(MANIFEST)
    scan = load_done(FACESCAN)
    todo = [(r["sample_id"], scan[r["sample_id"]], r.get("bbox"))
            for r in mani.values()
            if (args.status == "all" or r["status"] == args.status)
            and r["sample_id"] in scan and scan[r["sample_id"]].get("frames")]
    todo.sort(key=lambda t: t[0])
    if args.limit:
        todo = todo[:args.limit]

    # 断点续跑：已经成功打包过的条目直接复用，只补没成的
    prev_path = PACK / "items.json"
    prev = json.loads(prev_path.read_text(encoding="utf-8")) if prev_path.exists() else []
    done_ids = {e["sample_id"] for e in prev
                if (PACK / "videos" / f"{e['sample_id']}.mp4").exists()}
    todo = [t for t in todo if t[0] not in done_ids]
    print(f"待打包 {len(todo)} 条（已完成 {len(done_ids)}）", flush=True)

    entries = [e for e in prev if e["sample_id"] in done_ids]
    errors = []
    with Pool(args.workers) as pool:
        for n, e in enumerate(pool.imap_unordered(process, todo, chunksize=2), 1):
            (errors if e.get("error") else entries).append(e)
            if n % 25 == 0 or n == len(todo):
                print(f"  {n}/{len(todo)}  失败 {len(errors)}", flush=True)

    entries.sort(key=lambda e: (e["source"], e["sample_id"]))
    (PACK / "items.json").write_text(
        json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    if errors:
        (PACK / "errors.json").write_text(
            json.dumps(errors, ensure_ascii=False, indent=1), encoding="utf-8")

    vsize = sum(f.stat().st_size for f in (PACK / "videos").glob("*.mp4"))
    fsize = sum(f.stat().st_size for f in (PACK / "faces").glob("*.jpg"))
    print(f"\n条目 {len(entries)}，失败 {len(errors)}")
    print(f"视频 {vsize/1024/1024:.1f} MB，人脸图 {fsize/1024/1024:.1f} MB")
    print(f"候选数分布: {dict(collections.Counter(len(e['candidates']) for e in entries))}")


if __name__ == "__main__":
    main()
