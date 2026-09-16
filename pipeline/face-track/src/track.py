"""逐帧人脸轨迹：在 visual.mp4 上跟住说话人，产出 out/tracks/<样本>.json。

**只借 manifest 的「身份」，不借它的「坐标」。** `manifest.jsonl` 里的 bbox 与
source_time 是在**原始数据集视频**的坐标系上算的，而 visual.mp4 已经过
chsims 裁字幕、iemocap 裁黑边、recrop_visual 重裁——两者坐标系对不上，
直接拿来用会错位。这里改成：

    身份模板 ← frames/<样本>.jpg（已人工核对过的说话人脸）→ SFace 128 维特征
    轨迹     ← visual.mp4 逐帧 YuNet 检测，每个候选脸与模板算余弦相似度

于是完全绕开坐标系问题，同时白拿了那 3440 条已人工核对的说话人身份。

断点续跑：输出文件已存在就跳过，重跑不会重算。
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import trackcore as tc
from datapaths import FRAMES_DIR, MEDIA_DIR

MANIFEST = FRAMES_DIR / "out" / "manifest.jsonl"
FRAMES = FRAMES_DIR / "out" / "frames"
YUNET = FRAMES_DIR / "models" / "face_detection_yunet_2023mar.onnx"
SFACE = FRAMES_DIR / "models" / "face_recognition_sface_2021dec.onnx"

OUT = Path(__file__).resolve().parents[1] / "out"
TRACKS = OUT / "tracks"

_det = None
_rec = None


def detector(size):
    """YuNet 检测器。输入尺寸随视频变，复用同一个实例避免反复建图。"""
    global _det
    import cv2
    if _det is None:
        _det = cv2.FaceDetectorYN.create(str(YUNET), "", size, tc.MIN_DET, 0.3, 5000)
    _det.setInputSize(size)
    return _det


def recognizer():
    global _rec
    import cv2
    if _rec is None:
        _rec = cv2.FaceRecognizerSF.create(str(SFACE), "")
    return _rec


def _faces(frame):
    """检测一帧，返回 [{"bbox": [...], "kps": [...], "det": float}, ...]。"""
    import cv2  # noqa: F401
    h, w = frame.shape[:2]
    _, raw = detector((w, h)).detect(frame)
    if raw is None:
        return []
    out = []
    for r in raw:
        out.append({
            "bbox": [float(v) for v in r[0:4]],
            "kps": [float(v) for v in r[4:14]],
            "det": float(r[14]),
            "_row": r,
        })
    return out


def _embed(frame, face):
    """L2 归一化的 128 维 SFace 特征。"""
    import numpy as np
    aligned = recognizer().alignCrop(frame, face["_row"])
    feat = recognizer().feature(aligned).flatten().astype("float32")
    n = float(np.linalg.norm(feat))
    return feat / n if n else feat


def template(sample_id):
    """从已核对的说话人静帧算身份模板。静帧是 512 见方的人脸特写，检测很稳。"""
    import cv2
    p = FRAMES / f"{sample_id}.jpg"
    if not p.exists():
        return None, "frame_missing"
    img = cv2.imread(str(p))
    if img is None:
        return None, "frame_unreadable"
    faces = _faces(img)
    if not faces:
        return None, "no_face_in_frame"
    face = max(faces, key=lambda f: f["bbox"][2] * f["bbox"][3])
    return _embed(img, face), None


def read_video(path):
    import cv2
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    return frames, (fps or 25.0)


def process(sample_id):
    import numpy as np
    out_path = TRACKS / f"{sample_id}.json"
    if out_path.exists():
        return "skip"

    video = MEDIA_DIR / "out" / "media" / sample_id / "visual.mp4"
    if not video.exists():
        _write(out_path, sample_id, 0, 0, None, None, {}, "drop", ["video_missing"])
        return "drop"

    tmpl, err = template(sample_id)
    if tmpl is None:
        _write(out_path, sample_id, 0, 0, None, None, {}, "drop", [err])
        return "drop"

    frames, fps = read_video(video)
    if not frames:
        _write(out_path, sample_id, fps, 0, None, None, {}, "drop", ["no_frames"])
        return "drop"

    h, w = frames[0].shape[:2]

    # 第一遍：与参考静帧比。静帧来自原始视频的另一个时刻、另一种光照，
    # 而 visual.mp4 重裁重编码过，相似度系统性偏低——实测有样本对静帧
    # 中位只有 0.258，对片内自己的脸却是 0.776。所以这遍只用来找锚点。
    cands = []
    embeds = []
    for frame in frames:
        faces = _faces(frame)
        row = []
        for f in faces:
            e = _embed(frame, f)
            f["sim"] = f["sim_ref"] = float(np.dot(e, tmpl))
            f.pop("_row", None)
            row.append(e)
        cands.append(faces)
        embeds.append(row)

    cands = _second_pass(cands, embeds, h)
    crop, stats, status, reasons = tc.build(cands, fps, w, h)
    _write(out_path, sample_id, fps, len(frames), (w, h), crop, stats, status, reasons)
    return status


# 早期失败（视频缺失、静帧检不出脸）也要写出完整形状的 stats，
# 否则下游读 face_present_ratio 之类会 KeyError——判级失败不等于字段可以少。
EMPTY_STATS = {
    "detected": 0, "face_present_ratio": 0.0, "face_inside_ratio": 0.0, "anchors": 0,
    "max_gap_frames": 0, "max_gap_seconds": 0.0,
    "det_rate": 0.0, "mean_sim": 0.0, "mean_face_h_ratio": 0.0,
}


def _second_pass(cands, embeds, frame_h):
    """用片内自己的脸当第二模板，把角度光照难的帧认回来。

    模板只由**确认锚点**（对静帧相似度 >= ANCHOR_SIM）构成，不是由第一遍
    接受的全部帧构成——后者用的是宽松的 0.25 门限，若第一遍跟错了人，
    拿它建模板会自我强化那个错误。锚点不足就直接返回，不做第二遍。

    `sim` 取两个模板的较大值（用于挑人与接受），`sim_ref` 始终保留对静帧的
    那个值（用于数锚点），两者不能混。
    """
    import numpy as np
    track = tc.link_track(cands, frame_h)
    anchors = []
    for i, t in enumerate(track):
        if t is None or t["sim_ref"] < tc.ANCHOR_SIM:
            continue
        for f, e in zip(cands[i], embeds[i]):
            if abs(f["bbox"][0] - t["bbox"][0]) < 1 and abs(f["bbox"][1] - t["bbox"][1]) < 1:
                anchors.append(e)
                break
    if len(anchors) < tc.ANCHOR_MIN:
        return cands

    inner = np.mean(anchors, axis=0)
    n = float(np.linalg.norm(inner))
    if not n:
        return cands
    inner /= n
    for row, erow in zip(cands, embeds):
        for f, e in zip(row, erow):
            f["sim"] = max(f["sim_ref"], float(np.dot(e, inner)))
    return cands


def _write(path, sample_id, fps, n_frames, wh, crop, stats, status, reasons):
    path.parent.mkdir(parents=True, exist_ok=True)
    stats = {**EMPTY_STATS, **(stats or {})}
    rec = {
        "sample_id": sample_id,
        "fps": round(float(fps), 6),
        "n_frames": n_frames,
        "w": wh[0] if wh else 0,
        "h": wh[1] if wh else 0,
        "crop": crop,
        "stats": stats,
        "status": status,
        "reasons": reasons,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)          # 原子落盘，中断不会留下半个文件


def load_samples(limit, samples_file):
    if samples_file:
        return [s.strip() for s in Path(samples_file).read_text().split() if s.strip()]
    ids = []
    with open(MANIFEST, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                ids.append(json.loads(line)["sample_id"])
    ids.sort()
    return ids[:limit] if limit else ids


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--of", type=int, default=1)
    ap.add_argument("--workers", type=int, default=int(os.environ.get("SLURM_CPUS_PER_TASK", 8)))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--samples", default="")
    args = ap.parse_args()

    ids = load_samples(args.limit, args.samples)
    mine = [s for i, s in enumerate(ids) if i % args.of == args.shard]
    print(f"分片 {args.shard}/{args.of}: {len(mine)} 条，{args.workers} 进程", flush=True)

    from concurrent.futures import ProcessPoolExecutor
    from collections import Counter
    tally = Counter()
    with ProcessPoolExecutor(args.workers) as ex:
        for i, status in enumerate(ex.map(process, mine, chunksize=1), 1):
            tally[status] += 1
            if i % 50 == 0:
                print(f"  {i}/{len(mine)} {dict(tally)}", flush=True)
    print("完成:", dict(tally), flush=True)


if __name__ == "__main__":
    main()
