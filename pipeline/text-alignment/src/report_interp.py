import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from datapaths import ALIGN_DIR  # noqa: E402
OUT_DIR = ALIGN_DIR / "out"
import json, collections
rows=[json.loads(l) for l in open(OUT_DIR / "pilot.jsonl") if json.loads(l)["status"]=="ok"]
interp=[(r["sample_id"], [w["t"] for w in r["words"] if w["c"]==-1]) for r in rows]
interp=[(s,w) for s,w in interp if w]
total=sum(len(w) for _,w in interp)
allw=sum(len(r["words"]) for r in rows)
print(f"总词数 {allw}，其中声学对齐 {allw-total}，插值定位 {total}（{total/allw:.1%}）")
print("插值的都是什么词:", collections.Counter(w for _,ws in interp for w in ws).most_common(8))
print()
for sid in ("meld_dia232_utt5","mustard_1_213","mosi_tStelxIAHjw_2"):
    r=next((x for x in rows if x["sample_id"]==sid), None)
    if not r: continue
    ws=r["words"]
    # 找出原先被丢的那类词现在的位置
    nums=[w for w in ws if any(c.isdigit() for c in w["t"])]
    print(f"{sid}: {r['text'][:60]!r}")
    for w in nums:
        print(f"    数字词 {w['t']!r} → {w['s']}–{w['e']}s  score={w['c']}")
