"""从单人桶抽取人脸特征、建角色原型库，并报告聚类离群情况。

离群率是个有用的信号：meld 的「反应镜头」（画面是听话人特写、说话人在画外）
会以错脸挂正确姓名的形式混进来，聚类时它们散成孤立点，正好被这一步量化出来。
"""
import argparse, collections, json, os, sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import FACESCAN, OUT, load_done, main_faces
from facelib import EMBEDS, build_gallery, embed, load_embeds, save_embeds
from pick_local import pick_best_frame, read_frame_at

GALLERY = OUT / "gallery.npz"
GALLERY_STATS = OUT / "gallery_stats.json"


def extract_one(rec):
    """返回 (sample_id, speaker_name, feat) 或 None。"""
    try:
        fr, face, _ = pick_best_frame(rec)
        if fr is None:
            return None
        frame = read_frame_at(rec["video_path"], fr["idx"])
        if frame is None:
            return None
        return rec["sample_id"], rec.get("speaker_name") or "?", embed(frame, face)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="meld,mustard")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--refresh", action="store_true", help="忽略已缓存的特征，重抽")
    args = ap.parse_args()

    sources = args.sources.split(",")
    scan = load_done(FACESCAN)
    recs = [r for r in scan.values()
            if r["source"] in sources and r.get("bucket") == "single"
            and r.get("speaker_name")]
    recs.sort(key=lambda r: r["sample_id"])
    print(f"单人桶样本 {len(recs)} 条（来源 {sources}）", flush=True)

    if EMBEDS.exists() and not args.refresh:
        sids, names, feats = load_embeds(EMBEDS)
        print(f"复用已缓存特征 {len(sids)} 条")
    else:
        sids, names, feats = [], [], []
        with Pool(args.workers) as pool:
            for n, res in enumerate(pool.imap_unordered(extract_one, recs, chunksize=4), 1):
                if res:
                    sids.append(res[0]); names.append(res[1]); feats.append(res[2])
                if n % 100 == 0 or n == len(recs):
                    print(f"  抽取 {n}/{len(recs)}", flush=True)
        feats = np.asarray(feats, dtype=np.float32)
        save_embeds(EMBEDS, sids, names, feats)
        print(f"特征已存 {EMBEDS}")

    by_name = {}
    idx_by_name = collections.defaultdict(list)
    for i, nm in enumerate(names):
        idx_by_name[nm].append(i)
    for nm, idxs in idx_by_name.items():
        by_name[nm] = ([sids[i] for i in idxs], feats[idxs])

    gallery, stats = build_gallery(by_name)
    np.savez_compressed(GALLERY, names=np.array(list(gallery)),
                        protos=np.asarray(list(gallery.values()), dtype=np.float32))
    GALLERY_STATS.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")

    usable = [n for n in stats if stats[n]["usable"]]
    tot_in = sum(s["n_in"] for s in stats.values())
    tot_keep = sum(s["n_keep"] for s in stats.values())
    print(f"\n角色 {len(stats)} 个，可用原型 {len(usable)} 个")
    print(f"入库人脸 {tot_in} 张，最大簇留下 {tot_keep} 张，离群 {tot_in-tot_keep} 张"
          f"（{100*(tot_in-tot_keep)/max(1,tot_in):.1f}%）")
    print(f"\n{'角色':16}{'入库':>6}{'留存':>6}{'离群':>6}  可用")
    for nm, s in sorted(stats.items(), key=lambda x: -x[1]["n_in"])[:16]:
        print(f"{nm:16}{s['n_in']:>6}{s['n_keep']:>6}{s['n_in']-s['n_keep']:>6}  "
              f"{'是' if s['usable'] else '否'}")
    print(f"\n原型库 -> {GALLERY}，明细 -> {GALLERY_STATS}")


if __name__ == "__main__":
    main()
