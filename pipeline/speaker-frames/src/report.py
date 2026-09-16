"""汇总 facescan / manifest 的状态，给出分桶、成本与缺口一览。"""
import argparse, collections, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import FACESCAN, FRAMES, MANIFEST, load_done
from resolve import load_pool


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(MANIFEST))
    args = ap.parse_args()

    pool = list(load_pool())
    scan = load_done(FACESCAN)
    mani = load_done(args.manifest)

    print(f"样本池 {len(pool)} 条 | 已扫描 {len(scan)} | manifest {len(mani)}\n")

    print("== 分桶（facescan） ==")
    b = collections.Counter((r["source"], r.get("bucket")) for r in scan.values())
    srcs = sorted({s for s, _ in b})
    print(f"{'source':10}{'single':>9}{'multi':>9}{'none':>7}{'合计':>8}")
    for s in srcs:
        row = [b[(s, k)] for k in ("single", "multi", "none")]
        print(f"{s:10}{row[0]:>9}{row[1]:>9}{row[2]:>7}{sum(row):>8}")
    tot = [sum(b[(s, k)] for s in srcs) for k in ("single", "multi", "none")]
    print(f"{'总计':8}{tot[0]:>9}{tot[1]:>9}{tot[2]:>7}{sum(tot):>8}")

    if mani:
        print("\n== 产出状态（manifest） ==")
        m = collections.Counter((r["source"], r["status"]) for r in mani.values())
        msrc = sorted({s for s, _ in m})
        print(f"{'source':10}{'ok':>7}{'needs_review':>14}{'failed':>8}{'合计':>8}")
        for s in msrc:
            row = [m[(s, k)] for k in ("ok", "needs_review", "failed")]
            print(f"{s:10}{row[0]:>7}{row[1]:>14}{row[2]:>8}{sum(row):>8}")
        meth = collections.Counter(r["method"] for r in mani.values())
        print("\n方法分布:", dict(meth))
        miss = [sid for sid, _ in pool if sid not in mani]
        print(f"尚未产出 {len(miss)} 条", miss[:5])
        nofile = [r["sample_id"] for r in mani.values()
                  if r.get("frame_path") and not (FRAMES.parent / r["frame_path"]).exists()]
        if nofile:
            print(f"⚠ manifest 有记录但图不存在 {len(nofile)} 条", nofile[:5])


if __name__ == "__main__":
    main()
