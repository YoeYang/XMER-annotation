#!/usr/bin/env python3
"""同一个样本、多位标注者的曲线对照图。

每个模态一行，把几个人的曲线叠在一起，用来看标注者之间的一致性，
以及有没有人把连续标注做成了「摆一个点就不动」。

用法：
  python plot_annotator_compare.py --sample <sample_id> \
      --export 名字=导出.json --export 名字=导出.json --out DIR
"""
import argparse
import json
from pathlib import Path

import matplotlib
import numpy as np
from scipy.signal import savgol_filter

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# 服务器上没有中文字体，图内一律用英文，避免渲染成方块
MODALITIES = [("visual", "Visual only"), ("audio", "Audio only"),
              ("text", "Text only"), ("audiovisual", "Full video")]
PALETTE = ["#c65d3b", "#2f6f6a", "#3a6ea5", "#b08a2e", "#7a5c8f"]
HW_MIN, HW_MAX = 0.015, 0.22
SMOOTH_WINDOW, SMOOTH_ORDER = 11, 2

plt.rcParams["axes.unicode_minus"] = False


def smooth(y):
    if len(y) < SMOOTH_ORDER + 2:
        return y
    win = min(SMOOTH_WINDOW, len(y) if len(y) % 2 else len(y) - 1)
    return y if win <= SMOOTH_ORDER else savgol_filter(y, win, SMOOTH_ORDER)


def latest_attempts(path):
    """每个任务取最新一次已提交的轮次。"""
    data = json.load(open(path, encoding="utf-8"))
    attempts = {a["attempt_id"]: a for a in data["attempts"]}
    best = {}
    for sub in data["submissions"]:
        tid = sub["task_id"]
        if tid not in best or sub["revision"] > best[tid]["revision"]:
            best[tid] = sub
    return {tid: attempts[s["attempt_id"]] for tid, s in best.items()}


def series(attempt):
    smp = sorted((s for s in attempt["samples"] if s.get("is_valid", True)),
                 key=lambda s: s["media_time"])
    t = np.array([s["media_time"] for s in smp], dtype=float)
    v = np.array([s["valence"] for s in smp], dtype=float)
    a = np.array([s["arousal"] for s in smp], dtype=float)
    return t, v, a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", required=True)
    ap.add_argument("--export", action="append", required=True,
                    help="名字=导出文件，可给多次")
    ap.add_argument("--out", default=".")
    args = ap.parse_args()

    people = []
    for item in args.export:
        name, _, path = item.partition("=")
        people.append((name, latest_attempts(path)))

    fig, axes = plt.subplots(len(MODALITIES), 1, figsize=(10, 9), sharex=True)
    tmax = 0.0
    for ax, (modality, label) in zip(axes, MODALITIES):
        tid = f"{args.sample}::{modality}"
        for i, (name, subs) in enumerate(people):
            if tid not in subs:
                continue
            t, v, a = series(subs[tid])
            if len(t) < 2:
                continue
            tmax = max(tmax, t.max())
            colour = PALETTE[i % len(PALETTE)]
            hw = smooth(HW_MIN + (np.clip(a, -1, 1) + 1) / 2 * (HW_MAX - HW_MIN))
            vs = smooth(v)
            ax.fill_between(t, vs - hw, vs + hw, color=colour, alpha=0.25, linewidth=0)
            ax.plot(t, vs, color=colour, linewidth=1.6,
                    label=f"{name} ({len(t)} pts)")
        ax.axhline(0, color="#aaa", lw=0.8, ls="--", zorder=0)
        ax.set_ylim(-1.05, 1.05)
        ax.set_ylabel("valence")
        ax.set_title(label, fontsize=11, loc="left", pad=6)
        ax.legend(loc="upper right", frameon=False, fontsize=8)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    axes[-1].set_xlim(0, tmax)
    axes[-1].set_xlabel("time (s)")
    fig.suptitle(f"{args.sample} — annotator comparison", fontsize=13)
    fig.text(0.5, 0.005, "line = valence, band width = arousal (wider = more aroused)",
             ha="center", fontsize=8, color="#888")
    fig.tight_layout(rect=(0, 0.02, 1, 0.98))

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"compare_{args.sample}.png"
    fig.savefig(path, dpi=150)
    print("wrote", path)


if __name__ == "__main__":
    main()
