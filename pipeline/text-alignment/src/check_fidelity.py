"""核对：对齐输出的词序列是否与数据集转录稿逐词一致，无增无删无改。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from datapaths import ALIGN_DIR  # noqa: E402
OUT_DIR = ALIGN_DIR / "out"
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from align import tokenize

rows = [json.loads(l) for l in open(OUT_DIR / "pilot.jsonl") if json.loads(l)["status"] == "ok"]
lost_total = 0
problem = []
for r in rows:
    expected = tokenize(r["text"], chinese=False)
    got = [w["t"] for w in r["words"]]
    if expected != got:
        missing = [w for w in expected if w not in got]
        problem.append((r["sample_id"], r["source"], len(expected), len(got), missing[:6]))
        lost_total += len(expected) - len(got)

print(f"核对 {len(rows)} 条")
print(f"逐词完全一致: {len(rows) - len(problem)}")
print(f"有出入: {len(problem)}，合计少了 {lost_total} 个词\n")
for sid, src, exp, got, missing in problem[:12]:
    print(f"  {src:<8}{sid:<32} 期望{exp:>3} 实得{got:>3}  丢失示例: {missing}")
