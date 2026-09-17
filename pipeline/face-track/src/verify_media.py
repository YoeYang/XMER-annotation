"""素材建完后的验收：五路齐全、时长一致、该有的都有，该没有的确实没有。

建素材的作业只报「ok / skip / fail」的计数，那不够——skip 里既有
「轨迹阶段就判死、本来就不该建」的，也可能混进「这次没跑到」的。
两者差一个字，后果差很多：前者正常，后者会让某个样本只有四个模态，
而分析时才发现。

用法：python3 src/verify_media.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "out"
TRACKS, MEDIA = ROOT / "tracks", ROOT / "media_v3"
FILES = ("face.mp4", "body.mp4", "visual.mp4", "audiovisual.mp4", "audio.m4a")
TOLERANCE = 0.030


def main() -> int:
    dropped = {l.strip() for l in (ROOT / "dropped.txt").read_text().split() if l.strip()}
    tally = Counter()
    problems = []

    for track in sorted(TRACKS.glob("*.json")):
        sid = track.stem
        status = json.loads(track.read_text(encoding="utf-8"))["status"]
        built = (MEDIA / sid / "build.json").exists()

        if status == "drop":
            tally["轨迹判死"] += 1
            if built:
                problems.append(f"{sid}: 轨迹判死却建出了素材")
            continue
        if sid in dropped:
            tally["人工剔除"] += 1
            continue
        if not built:
            # 该建没建——这才是真正要拦的那种
            tally["缺素材"] += 1
            problems.append(f"{sid}: status={status} 却没有 build.json")
            continue

        rec = json.loads((MEDIA / sid / "build.json").read_text(encoding="utf-8"))
        missing = [f for f in FILES if not (MEDIA / sid / f).exists()]
        if missing:
            problems.append(f"{sid}: 缺 {missing}")
            tally["文件不全"] += 1
        elif rec["spread"] > TOLERANCE:
            problems.append(f"{sid}: 五路时长极差 {rec['spread']:.3f}s > {TOLERANCE}")
            tally["时长不齐"] += 1
        else:
            tally["完好"] += 1

    print("验收结果：")
    for k, v in tally.most_common():
        print(f"  {k:8} {v:>5}")
    usable = tally["完好"]
    print(f"\n可用样本 {usable} 条 × 5 模态 = {usable*5} 个子任务")
    if problems:
        print(f"\n有问题的 {len(problems)} 条：")
        for p in problems[:20]:
            print("  " + p)
        return 1
    print("\n没有问题。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
