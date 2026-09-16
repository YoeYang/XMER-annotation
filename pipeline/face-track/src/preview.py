"""把裁剪框画出来，供人工核对。

每个样本出一张对照图：上排是原帧并画出裁剪框（绿=该帧认出了人脸，
红=没认出），下排是标注者在 face 子任务里**实际会看到的画面**——
认出人脸的帧裁框内画面，**没认出的帧一律黑屏**，绝不把镜头里的另一个人
当成说话人给标注者看。

用法：
    /usr/bin/python3 src/preview.py --samples out/pilot50.txt --n 8 --out out/preview
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from datapaths import MEDIA_DIR

TRACKS = Path(__file__).resolve().parents[1] / "out" / "tracks"
COLS = 8
THUMB = 220


def sheet(sample_id, out_dir):
    import cv2
    import numpy as np

    rec = json.loads((TRACKS / f"{sample_id}.json").read_text(encoding="utf-8"))
    crop = rec.get("crop")
    # 判死的样本可能一帧都没认出人脸（静帧本身就检不出）。这类照样要出图
    # 供人工核对——不然最该看的 14 条反而看不到。
    no_crop = not crop

    cap = cv2.VideoCapture(str(MEDIA_DIR / "out" / "media" / sample_id / "visual.mp4"))
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    if not frames:
        return None

    n = min(COLS, len(frames))
    idxs = [round(i * (len(frames) - 1) / max(1, n - 1)) for i in range(n)]
    side = crop["side"] if crop else 0
    top, bottom = [], []
    for i in idxs:
        fr = frames[i].copy()
        if no_crop:
            h, w = fr.shape[:2]
            top.append(cv2.resize(fr, (int(THUMB * w / h), THUMB)))
            bottom.append(np.zeros((THUMB, THUMB, 3), dtype="uint8"))
            continue
        c = crop["frames"][min(i, len(crop["frames"]) - 1)]
        x0, y0 = int(c["cx"] - side / 2), int(c["cy"] - side / 2)
        x1, y1 = int(x0 + side), int(y0 + side)
        color = (0, 200, 0) if c["present"] else (0, 0, 255)
        cv2.rectangle(fr, (x0, y0), (x1, y1), color, 4)
        h, w = fr.shape[:2]
        top.append(cv2.resize(fr, (int(THUMB * w / h), THUMB)))

        if not c["present"]:
            # 认不出目标说话人 -> 黑屏。标注者宁可看黑屏，也不能看错人。
            bottom.append(np.zeros((THUMB, THUMB, 3), dtype="uint8"))
        else:
            x0c, y0c = max(0, x0), max(0, y0)
            x1c, y1c = min(w, x1), min(h, y1)
            patch = frames[i][y0c:y1c, x0c:x1c]
            if patch.size == 0:
                patch = np.zeros((THUMB, THUMB, 3), dtype="uint8")
            bottom.append(cv2.resize(patch, (THUMB, THUMB)))

    # 上下两排各自等高拼接，再按最大宽度补齐
    row1 = np.hstack(top)
    row2 = np.hstack(bottom)
    width = max(row1.shape[1], row2.shape[1])
    def pad(img):
        if img.shape[1] == width:
            return img
        return np.hstack([img, np.zeros((img.shape[0], width - img.shape[1], 3), "uint8")])
    sheet_img = np.vstack([pad(row1), pad(row2)])

    st = rec["stats"]
    mode = crop["mode"] if crop else "no-crop"
    label = (f'{sample_id}  [{rec["status"]}]  mode={mode}  side={side:.0f}  '
             f'present={st["face_present_ratio"]:.0%} black={1-st["face_present_ratio"]:.0%}  '
             f'sim={st["mean_sim"]:.2f}  inside={st.get("face_inside_ratio",0):.0%}')
    bar = np.zeros((34, width, 3), dtype="uint8")
    cv2.putText(bar, label, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    sheet_img = np.vstack([bar, sheet_img])

    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{sample_id}.jpg"
    cv2.imwrite(str(p), sheet_img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--samples", required=True)
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--out", default="out/preview")
    ap.add_argument("--pick", default="", help="逗号分隔的样本 id，给定则忽略 --n")
    args = ap.parse_args()

    ids = [s.strip() for s in Path(args.samples).read_text().split() if s.strip()]
    if args.pick:
        ids = [s.strip() for s in args.pick.split(",") if s.strip()]
    else:
        # 每个数据集各取几条，别全是同一个源
        by = {}
        for s in ids:
            by.setdefault(s.split("_")[0], []).append(s)
        ids = []
        per = max(1, args.n // max(1, len(by)))
        for src in sorted(by):
            ids += by[src][:per]
        ids = ids[:args.n]

    out_dir = Path(args.out)
    for s in ids:
        p = sheet(s, out_dir)
        print(("OK   " if p else "跳过 ") + s + (f"  -> {p}" if p else ""))


if __name__ == "__main__":
    main()
