"""构建 V3 的五模态素材，并把五路时长对齐到完全一致。

产出 `out/media_v3/<样本>/{face.mp4, body.mp4, visual.mp4, audio.m4a, audiovisual.mp4}`。
**不覆盖旧素材** —— 旧的 `08-material-prep/out/media` 原样保留，确认没问题再删。

## 为什么必须对齐

现有四路是各自编码的，同一样本的时长并不一致：AAC 按 1024 采样一帧对齐
（44.1kHz 下约 23ms 粒度），H.264 按 GOP 收尾，各自向上取整的量不同。
全量实测三模态极差中位 0.020s、**最大 0.700s**，其中 16 条已经超过前端
0.25 秒的容差。V3 还要再加 face / body 两路，不对齐会更乱。

后果不只是前端拒绝打开：同一样本五个模态**共用一条时间轴**，长度不等的话
跨模态合并曲线时对不齐，`GROUP BY source_id` 聚出来的东西没法直接比。

## 怎么对齐

```
N = min(visual 实际帧数, audiovisual 实际帧数, floor(音频时长 × fps))
目标时长 = N / fps
```

**帧数取「实际可解码」而不是容器声称的。** 容器元数据会虚报——handover 记过
iemocap「声称 266 帧实际只有 52 帧」——只按时长算 N 会超出源真有的帧，
ffmpeg 就少写几帧，时长对不上。试点里 3 条栽在这。

**fps 必须用精确有理数。** cv2 给的是浮点 23.976023976…，直接传给 ffmpeg
时基对不上，输出会差一帧（试点里 7 条栽在这）。这里用
`Fraction(fps).limit_denominator()` 还原成 `24000/1001` 这样的分数再传。

四路视频**严格**输出 N 帧、同一个 fps 分数，时长因此严格相等。音频受 AAC 帧长限制，
只能逼近到一个音频帧以内——这是编码格式的硬约束，不是偷工减料，
`verify()` 会把实际残差量出来。

x86 上能编码 H.264 的只有装在 conflict-sampling-x86 里的静态 ffmpeg，
见记忆 `xmer-roihu-env-slurm`。
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import render as R
from datapaths import MEDIA_DIR

TRACKS = Path(__file__).resolve().parents[1] / "out" / "tracks"
OUT = Path(__file__).resolve().parents[1] / "out" / "media_v3"
FFMPEG = R.FFMPEG

TOLERANCE = 0.030
"""五路时长的允许残差。

四路视频严格相等（同 N 帧同 fps）；音频受 AAC 帧长约束，
44.1kHz 下一帧 1024 采样 ≈ 23ms，取 30ms 留一点余量。
比现状最坏的 0.700s 好了 23 倍，也远在前端 0.25s 容差之内。
"""


def probe(path):
    """返回时长秒数；读不出返回 None。"""
    out = subprocess.run([str(FFMPEG), "-i", str(path)],
                         capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def _run(args):
    return subprocess.run([str(FFMPEG), "-hide_banner", "-loglevel", "error",
                           "-y"]
                          + args, capture_output=True, text=True)


def build(sample_id, size=R.OUT_SIZE, crf=20):
    rec_path = TRACKS / f"{sample_id}.json"
    if not rec_path.exists():
        return None, "no_track"
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    if rec["status"] == "drop" or not rec.get("crop"):
        return None, f"status={rec['status']}"

    src = MEDIA_DIR / "out" / "media" / sample_id
    audio_dur = probe(src / "audio.m4a")
    if audio_dur is None:
        return None, "probe_failed"

    fps = rec["fps"]
    rate = R.exact_fps(fps)

    # 帧数以**实际可解码**为准，容器声称的不可信
    n_visual = R._frame_count(src / "visual.mp4")
    n_av = R._frame_count(src / "audiovisual.mp4")
    if n_visual <= 0 or n_av <= 0:
        return None, f"decode_failed visual={n_visual} av={n_av}"

    n_frames = min(n_visual, n_av, int(audio_dur * fps + 1e-9))
    if n_frames < 2:
        return None, f"too_short n={n_frames}"
    target = n_frames / fps

    out_dir = OUT / sample_id
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / ".tmp"
    tmp.mkdir(exist_ok=True)

    # face / body 由 render.py 出，天然就是源视频的帧序列，再截到 N 帧
    info, err = R.render(sample_id, tmp / "face.mp4", size, crf)
    if err:
        return None, f"face: {err}"
    info, err = R.render_body(sample_id, tmp / "body.mp4", crf)
    if err:
        return None, f"body: {err}"

    jobs = [
        (tmp / "face.mp4", out_dir / "face.mp4", "v"),
        (tmp / "body.mp4", out_dir / "body.mp4", "v"),
        (src / "visual.mp4", out_dir / "visual.mp4", "v"),
        (src / "audiovisual.mp4", out_dir / "audiovisual.mp4", "av"),
        (src / "audio.m4a", out_dir / "audio.m4a", "a"),
    ]
    for source, dest, kind in jobs:
        if kind == "v":
            # `-t` 是关键：只给 `-frames:v` 的话帧数对了，但容器会按源时间戳
            # 把最后一帧的时长多算一帧，时长报出来差 0.04s。实测过五种写法，
            # 只有显式限定输出时长才真正对齐（-fps_mode cfr 和 setpts 都无效）。
            args = ["-r", rate, "-i", str(source), "-an",
                    "-frames:v", str(n_frames), "-r", rate, "-t", f"{target:.6f}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
                    "-pix_fmt", "yuv420p", str(dest)]
        elif kind == "av":
            args = ["-r", rate, "-i", str(source),
                    "-frames:v", str(n_frames), "-r", rate,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "128k", "-t", f"{target:.6f}", str(dest)]
        else:
            args = ["-i", str(source), "-vn", "-c:a", "aac", "-b:a", "128k",
                    "-t", f"{target:.6f}", str(dest)]
        r = _run(args)
        if r.returncode != 0:
            return None, f"{dest.name}: {r.stderr.strip()[:120]}"

    for f in tmp.iterdir():
        f.unlink()
    tmp.rmdir()

    return verify(sample_id, out_dir, n_frames, fps, target)


def verify(sample_id, out_dir, n_frames, fps, target):
    """硬断言：五路时长必须一致，视频帧数必须等于 N。不一致就判失败。"""
    durs = {}
    for f in ("face.mp4", "body.mp4", "visual.mp4", "audiovisual.mp4", "audio.m4a"):
        d = probe(out_dir / f)
        if d is None:
            return None, f"{f}: 读不出"
        durs[f] = d

    spread = max(durs.values()) - min(durs.values())
    if spread > TOLERANCE:
        return None, ("时长不一致 极差=%.3fs " % spread
                      + " ".join(f"{k.split('.')[0]}={v:.3f}" for k, v in durs.items()))

    for f in ("face.mp4", "body.mp4", "visual.mp4", "audiovisual.mp4"):
        got = R._frame_count(out_dir / f)
        if got != n_frames:
            return None, f"{f}: 帧数 {got} != {n_frames}"

    return {"sample_id": sample_id, "n_frames": n_frames, "fps": round(fps, 6),
            "duration": round(target, 6), "spread": round(spread, 4),
            "durations": {k: round(v, 3) for k, v in durs.items()}}, None


def process(sample_id):
    done = OUT / sample_id / "build.json"
    if done.exists():
        return "skip", None
    info, err = build(sample_id)
    if err:
        # 轨迹阶段就判死的样本是预期内的跳过，不是构建失败
        return ("skip", None) if err.startswith("status=") else ("fail", f"{sample_id}: {err}")
    (OUT / sample_id / "build.json").write_text(
        json.dumps(info, ensure_ascii=False), encoding="utf-8")
    return "ok", None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--of", type=int, default=1)
    ap.add_argument("--workers", type=int,
                    default=int(os.environ.get("SLURM_CPUS_PER_TASK", 8)))
    ap.add_argument("--samples", default="")
    args = ap.parse_args()

    if args.samples:
        p = Path(args.samples)
        ids = ([s.strip() for s in p.read_text().split() if s.strip()] if p.exists()
               else [s.strip() for s in args.samples.split(",") if s.strip()])
    else:
        ids = sorted(p.stem for p in TRACKS.glob("*.json"))

    mine = [s for i, s in enumerate(ids) if i % args.of == args.shard]
    print(f"分片 {args.shard}/{args.of}: {len(mine)} 条，{args.workers} 进程", flush=True)

    from concurrent.futures import ProcessPoolExecutor
    from collections import Counter
    tally, fails = Counter(), []
    with ProcessPoolExecutor(args.workers) as ex:
        for i, (status, msg) in enumerate(ex.map(process, mine, chunksize=1), 1):
            tally[status] += 1
            if msg:
                fails.append(msg)
            if i % 50 == 0:
                print(f"  {i}/{len(mine)} {dict(tally)}", flush=True)
    print("完成:", dict(tally), flush=True)
    for m in fails[:40]:
        print("  失败:", m, flush=True)


if __name__ == "__main__":
    main()
