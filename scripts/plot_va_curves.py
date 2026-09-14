#!/usr/bin/env python3
"""Plot emotion-over-time curves from a V-A annotation export.

x = media_time (s), y = valence (+ positive emotion / - negative emotion),
a filled band around the valence line encodes arousal: the wider the band,
the higher the arousal (river-thickness metaphor).

Produces three figures for one annotated sample:
  1. three single modalities overlaid (visual / audio / text)
  2. the full audiovisual annotation alone
  3. all four overlaid

Usage:
  python plot_va_curves.py <export.json> [--out DIR]
The export is a full local-storage dump {attempts, submissions, ...}.
For each EXAMPLE task the latest *submitted* annotation attempt is used.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import matplotlib
from scipy.signal import savgol_filter

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Savitzky-Golay smoothing: soften 10 Hz jitter without overshooting ±1
SMOOTH_WINDOW, SMOOTH_ORDER = 11, 2


def smooth(y: np.ndarray) -> np.ndarray:
    n = len(y)
    if n < SMOOTH_ORDER + 2:
        return y
    win = min(SMOOTH_WINDOW, n if n % 2 else n - 1)  # odd, <= n
    if win <= SMOOTH_ORDER:
        return y
    return savgol_filter(y, win, SMOOTH_ORDER)

# modality -> (display label, color)
MODALITY_STYLE = {
    "audiovisual": ("Full video", "#2f6f6a"),  # teal
    "visual": ("Visual only", "#c65d3b"),  # terracotta
    "audio": ("Audio only", "#3a6ea5"),  # blue
    "text": ("Text only", "#b08a2e"),  # gold
}
# band half-width (in valence units) mapped from arousal in [-1, 1]
HW_MIN, HW_MAX = 0.015, 0.22
BAND_ALPHA = 0.40

plt.rcParams["axes.unicode_minus"] = False


def arousal_to_halfwidth(arousal: np.ndarray) -> np.ndarray:
    a = np.clip((arousal + 1.0) / 2.0, 0.0, 1.0)  # -1..1 -> 0..1
    return HW_MIN + a * (HW_MAX - HW_MIN)


def pick_series(export: dict) -> dict:
    """Return {modality: {'t':[], 'v':[], 'a':[], 'task_id':..}} using the
    latest submitted annotation attempt per EXAMPLE task."""
    submissions = export.get("submissions", [])
    attempts = {a["attempt_id"]: a for a in export.get("attempts", [])}
    # latest submission per task_id (highest revision)
    latest_sub = {}
    for s in submissions:
        tid = s["task_id"]
        if tid not in latest_sub or s["revision"] > latest_sub[tid]["revision"]:
            latest_sub[tid] = s
    series = {}
    for tid, sub in latest_sub.items():
        att = attempts.get(sub["attempt_id"])
        if not att or not att.get("samples"):
            continue
        mod = att["modality"]
        smp = [s for s in att["samples"] if s.get("is_valid", True)]
        smp.sort(key=lambda s: s["media_time"])
        series[mod] = {
            "task_id": tid,
            "t": np.array([s["media_time"] for s in smp], dtype=float),
            "v": np.array([s["valence"] for s in smp], dtype=float),
            "a": np.array([s["arousal"] for s in smp], dtype=float),
        }
    return series


def draw_curve(ax, s: dict, color: str, label: str):
    t, v, a = s["t"], s["v"], s["a"]
    if len(t) < 1:
        return
    v = smooth(v)
    hw = smooth(arousal_to_halfwidth(a))
    # arousal band: filled ribbon whose vertical width tracks arousal
    ax.fill_between(t, v - hw, v + hw, color=color, alpha=BAND_ALPHA,
                    linewidth=0, zorder=2)
    # valence centerline for a precise read of the value
    ax.plot(t, v, color=color, linewidth=1.4, zorder=3, solid_capstyle="round")
    # legend handle
    ax.plot([], [], color=color, linewidth=6, alpha=0.6, label=label)


def style_axes(ax, tmax: float):
    ax.axhline(0, color="#999", lw=0.8, ls="--", zorder=0)
    ax.set_xlim(0, tmax)
    ax.set_ylim(-1.05, 1.05)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("valence")
    ax.text(-0.06, 0.97, "positive +", transform=ax.transAxes,
            va="top", ha="center", rotation=90, color="#c65d3b", fontsize=9)
    ax.text(-0.06, 0.03, "negative −", transform=ax.transAxes,
            va="bottom", ha="center", rotation=90, color="#3a6ea5", fontsize=9)
    ax.grid(True, axis="x", color="#eee", lw=0.6)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)


def draw_arousal_ref(ax):
    """Inset in the lower-right showing band width for low/mid/high arousal."""
    ins = ax.inset_axes([0.015, 0.70, 0.17, 0.26])
    ins.set_xlim(0, 3)
    ins.set_ylim(-0.35, 0.35)
    for i, av in enumerate((-0.6, 0.1, 0.8)):
        hw = arousal_to_halfwidth(np.array([av]))[0]
        x = np.array([i * 1.0 + 0.15, i * 1.0 + 0.85])
        y = np.zeros(2)
        ins.fill_between(x, y - hw, y + hw, color="#666", alpha=0.5, lw=0)
        ins.plot(x, y, color="#444", lw=1.0)
    ins.set_xticks([0.5, 1.5, 2.5])
    ins.set_xticklabels(["low", "mid", "high"], fontsize=7)
    ins.set_yticks([])
    ins.set_title("band width = arousal", fontsize=7.5, pad=2)
    for sp in ins.spines.values():
        sp.set_visible(False)
    ins.tick_params(length=0)


def render(export: dict, sample_id: str, outdir: Path) -> None:
    """One figure per sample: the four modality curves overlaid."""
    subset = {
        **export,
        "submissions": [
            s for s in export.get("submissions", [])
            if s["task_id"].split("::")[0] == sample_id
        ],
    }
    series = pick_series(subset)
    if not series:
        print("skip", sample_id, "(no submitted annotation)")
        return
    tmax = max(s["t"].max() for s in series.values())

    fig, ax = plt.subplots(figsize=(10, 5))
    for mod in ("audiovisual", "visual", "audio", "text"):
        if mod in series:
            lbl, col = MODALITY_STYLE[mod]
            draw_curve(ax, series[mod], col, lbl)
    style_axes(ax, tmax)
    ax.set_title("Emotion over time — all four annotations", fontsize=13, pad=12)
    ax.legend(loc="upper right", frameon=False, fontsize=9)
    draw_arousal_ref(ax)
    fig.text(0.5, 0.005,
             f"sample {sample_id} · annotator {export.get('annotator_id','?')}"
             f" · {len(series)}/4 modalities"
             " · band width encodes arousal (wider = more aroused)",
             ha="center", fontsize=8, color="#888")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    path = outdir / f"va_{sample_id}.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print("wrote", path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export")
    ap.add_argument("--out", default=".")
    ap.add_argument("--sample", help="只画这一个样本；不给就把导出里的样本全画")
    args = ap.parse_args()

    export = json.load(open(args.export, encoding="utf-8"))
    samples = sorted(
        {s["task_id"].split("::")[0] for s in export.get("submissions", [])}
    )
    if args.sample:
        if args.sample not in samples:
            sys.exit(f"导出里没有样本 {args.sample}")
        samples = [args.sample]
    if not samples:
        sys.exit("no annotated samples found in export")

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    for sample_id in samples:
        render(export, sample_id, outdir)
    print(f"共 {len(samples)} 个样本")


if __name__ == "__main__":
    main()
