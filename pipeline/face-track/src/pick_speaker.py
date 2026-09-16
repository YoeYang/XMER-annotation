"""给「静帧上检不出脸」的样本生成人工指认素材。

## 为什么需要人工指认

身份模板来自 `06` 阶段那张说话人静帧。少数样本的静帧分辨率太低或太糊，
YuNet 在正常门限下检不出脸——于是拿不到模板，视频**根本没被打开**就判死了。
而这些样本的视频里其实每帧都有脸。

**不因此放宽全局检测门限。** 那是拿 3440 条的判定口径去迁就十来条，不划算。
改为人工指认：由人告诉流水线「说话人是这张脸」，`track.py` 就从视频的那一帧、
那个框里建模板，检测标准一个字不改——在裁出来的小框上跑检测本来就比全图容易。

## 这里的低门限只用于「列候选给人看」

下面 `CANDIDATE_DET` 取得很低，是为了把画面里所有可能的脸都摆出来供人挑，
**不参与任何判定**。选中哪张由人决定，之后的流水线仍走正常门限。

产出 `out/pick/candidates.json`，图片直接内联成 base64——十来条样本的量，
省得再管一堆附件文件。
"""
import argparse
import base64
import io as _io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import trackcore as tc
from datapaths import FRAMES_DIR, MEDIA_DIR

OUT = Path(__file__).resolve().parents[1] / "out" / "pick"
YUNET = FRAMES_DIR / "models" / "face_detection_yunet_2023mar.onnx"
PORTRAITS = FRAMES_DIR / "out" / "frames"
MANIFEST = FRAMES_DIR / "out" / "manifest.jsonl"

CANDIDATE_DET = 0.15
"""列候选用的检测门限，**仅用于显示**。挑哪张由人决定，流水线仍走 tc.MIN_DET。"""

N_FRAMES = 4
"""每条样本取几帧给人看。太少怕正好都是侧脸，太多翻起来累。"""

FRAME_W = 480
CROP_PX = 96


def _jpeg(img, quality=72):
    import cv2
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(buf.tobytes()).decode() if ok else None


def _detect(img):
    import cv2
    h, w = img.shape[:2]
    det = cv2.FaceDetectorYN.create(str(YUNET), "", (w, h), CANDIDATE_DET, 0.3, 5000)
    _, raw = det.detect(img)
    if raw is None:
        return []
    return [
        {"bbox": [round(float(v), 1) for v in r[0:4]], "det": round(float(r[14]), 3)}
        for r in raw
    ]


def _crop(frame, bbox, margin=0.35):
    import cv2
    import numpy as np
    x, y, w, h = bbox
    cx, cy = x + w / 2, y + h / 2
    side = max(w, h) * (1 + 2 * margin)
    x0, y0 = int(round(cx - side / 2)), int(round(cy - side / 2))
    x1, y1 = int(round(x0 + side)), int(round(y0 + side))
    H, W = frame.shape[:2]
    pl, pt = max(0, -x0), max(0, -y0)
    pr, pb = max(0, x1 - W), max(0, y1 - H)
    patch = frame[max(0, y0):min(H, y1), max(0, x0):min(W, x1)]
    if patch.size == 0:
        return np.zeros((CROP_PX, CROP_PX, 3), dtype="uint8")
    if pl or pt or pr or pb:
        patch = cv2.copyMakeBorder(patch, pt, pb, pl, pr, cv2.BORDER_REPLICATE)
    return cv2.resize(patch, (CROP_PX, CROP_PX), interpolation=cv2.INTER_AREA)


def build(sample_id, names):
    import cv2

    video = MEDIA_DIR / "out" / "media" / sample_id / "visual.mp4"
    cap = cv2.VideoCapture(str(video))
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    if not frames:
        return None

    portrait = None
    p = PORTRAITS / f"{sample_id}.jpg"
    if p.exists():
        img = cv2.imread(str(p))
        if img is not None:
            img = cv2.resize(img, (200, 200), interpolation=cv2.INTER_AREA)
            portrait = _jpeg(img)

    picks = [round(i * (len(frames) - 1) / (N_FRAMES - 1)) for i in range(N_FRAMES)]
    out_frames = []
    for idx in sorted(set(picks)):
        frame = frames[idx]
        faces = _detect(frame)
        if not faces:
            continue
        shown = frame.copy()
        cands = []
        for k, f in enumerate(faces):
            x, y, w, h = [int(round(v)) for v in f["bbox"]]
            cv2.rectangle(shown, (x, y), (x + w, y + h), (0, 200, 255), 3)
            cv2.putText(shown, str(k + 1), (x, max(18, y - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2)
            cands.append({
                "k": k + 1,
                "bbox": f["bbox"],
                "det": f["det"],
                "crop": _jpeg(_crop(frame, f["bbox"]), 80),
            })
        hh, ww = shown.shape[:2]
        shown = cv2.resize(shown, (FRAME_W, int(FRAME_W * hh / ww)),
                           interpolation=cv2.INTER_AREA)
        out_frames.append({"i": idx, "img": _jpeg(shown, 68), "faces": cands})

    return {
        "id": sample_id,
        "name": names.get(sample_id),
        "portrait": portrait,
        "n_frames": len(frames),
        "wh": f"{frames[0].shape[1]}x{frames[0].shape[0]}",
        "frames": out_frames,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--samples", required=True)
    args = ap.parse_args()

    names = {}
    with MANIFEST.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                names[r["sample_id"]] = r.get("speaker_name")

    ids = [s.strip() for s in Path(args.samples).read_text().split() if s.strip()]
    items = []
    for sid in ids:
        rec = build(sid, names)
        if rec is None:
            print(f"跳过 {sid}：视频读不出", flush=True)
            continue
        n = sum(len(f["faces"]) for f in rec["frames"])
        print(f"OK   {sid:34s} {len(rec['frames'])} 帧 / {n} 个候选脸", flush=True)
        items.append(rec)

    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / "candidates.json"
    dest.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    size = dest.stat().st_size / 1024 / 1024
    print(f"\n{len(items)} 条 -> {dest} ({size:.1f}MB)")


if __name__ == "__main__":
    main()
