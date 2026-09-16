"""把人工核对驳回的 sample_id 从 manifest 里摘出来，以便换方法重跑。

用法：python3 src/requeue.py out/review/rejected.txt [--method gemini]
被驳回的记录会移到 manifest.rejected.jsonl 存档，主 manifest 里删掉，
下一次 pick_* 就会重新处理这些样本。
"""
import argparse, json, shutil, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import MANIFEST, load_done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rejected")
    ap.add_argument("--manifest", default=str(MANIFEST))
    args = ap.parse_args()

    bad = {l.strip() for l in open(args.rejected, encoding="utf-8") if l.strip()}
    recs = load_done(args.manifest)
    hit = [r for sid, r in recs.items() if sid in bad]
    if not hit:
        print("没有匹配到任何驳回项")
        return

    mpath = Path(args.manifest)
    shutil.copy(mpath, mpath.with_suffix(".jsonl.bak"))
    with open(mpath.with_name(mpath.stem + ".rejected.jsonl"), "a", encoding="utf-8") as f:
        for r in hit:
            r["status"] = "rejected"
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(mpath, "w", encoding="utf-8") as f:
        for sid, r in recs.items():
            if sid not in bad:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"摘出 {len(hit)} 条（原 manifest 已备份到 {mpath.name}.bak），可重跑")


if __name__ == "__main__":
    main()
