"""为存疑的 chsims 条目生成「唇动对照条」，供人工快速判断谁在说话。

单帧看不出谁在说话——说话的人可能恰好闭嘴，没说话的人可能恰好因表情张嘴。
把每一帧里各个候选人的嘴部并排铺开，谁的唇形在连续开合一眼就能看出来。
生成的图挂在核对页上，把「凭一张脸猜」变成「看唇动序列判断」。
"""
import argparse, json, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import FACESCAN, MANIFEST, OUT, ensure_dirs, faces_for_pick, load_done
from pick_local import read_frames_at

LIPS = OUT / "review" / "lips"
TILE_W, TILE_H = 110, 82
MAX_PEOPLE = 4


def make_strip(rec, chosen_bbox=None):
    """返回拼好的对照条；无可用帧时返回 None。"""
    import cv2
    idxs = [f["idx"] for f in rec["frames"]]
    frames = read_frames_at(rec["video_path"], idxs)
    rows = []
    for f in rec["frames"]:
        frame = frames.get(f["idx"])
        if frame is None:
            continue
        faces = sorted(faces_for_pick(f["faces"], rec["h"])[0], key=lambda x: x["bbox"][0])
        tiles = []
        for i, face in enumerate(faces[:MAX_PEOPLE], 1):
            x, y, w, h = face["bbox"]
            # 只取鼻尖到下巴：唇动最清楚，也避免被发型衣着干扰
            y0, y1 = int(y + h * 0.55), int(y + h * 1.15)
            x0, x1 = int(x - w * 0.1), int(x + w * 1.1)
            y0, x0 = max(0, y0), max(0, x0)
            y1, x1 = min(frame.shape[0], y1), min(frame.shape[1], x1)
            crop = frame[y0:y1, x0:x1]
            if crop.size == 0:
                continue
            crop = cv2.resize(crop, (TILE_W, TILE_H))
            # 标出流水线选中的那个人，人眼好对照
            picked = (chosen_bbox is not None
                      and abs(face["bbox"][0] - chosen_bbox[0]) < 3
                      and abs(face["bbox"][1] - chosen_bbox[1]) < 3)
            color = (80, 220, 80) if picked else (0, 200, 255)
            if picked:
                cv2.rectangle(crop, (0, 0), (TILE_W - 1, TILE_H - 1), color, 3)
            cv2.putText(crop, f"#{i}", (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1)
            tiles.append(crop)
        if not tiles:
            continue
        while len(tiles) < MAX_PEOPLE:
            tiles.append(np.zeros((TILE_H, TILE_W, 3), np.uint8))
        row = np.hstack(tiles)
        cv2.putText(row, f"{f['t']:.2f}s", (TILE_W * MAX_PEOPLE - 52, TILE_H - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (120, 255, 120), 1)
        rows.append(row)
    return np.vstack(rows) if rows else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", default="needs_review", help="给哪些状态的条目生成；all 为全部")
    ap.add_argument("--sources", default="chsims")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    import cv2
    ensure_dirs()
    LIPS.mkdir(parents=True, exist_ok=True)
    scan = load_done(FACESCAN)
    sources = args.sources.split(",")
    recs = [r for r in load_done(MANIFEST).values()
            if r["source"] in sources
            and (args.status == "all" or r["status"] == args.status)]
    recs.sort(key=lambda r: r["sample_id"])
    if args.limit:
        recs = recs[:args.limit]
    print(f"待生成 {len(recs)} 条唇动对照条", flush=True)

    n_ok = 0
    for n, m in enumerate(recs, 1):
        rec = scan.get(m["sample_id"])
        if not rec or not rec.get("frames"):
            continue
        strip = make_strip(rec, m.get("bbox"))
        if strip is None:
            continue
        cv2.imwrite(str(LIPS / f"{m['sample_id']}.jpg"), strip,
                    [cv2.IMWRITE_JPEG_QUALITY, 85])
        n_ok += 1
        if n % 50 == 0 or n == len(recs):
            print(f"  {n}/{len(recs)}", flush=True)
    print(f"生成 {n_ok} 张 -> {LIPS}")


if __name__ == "__main__":
    main()
