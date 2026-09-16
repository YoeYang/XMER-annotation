"""重裁「仅视觉」素材，去掉两处会干扰标注的画面元素。

chsims   片源自带硬字幕，在只看画面的模态里把台词提前透给标注者，
         直接破坏单模态隔离 —— 裁掉画面下缘。字幕不是按前缀分布的
         （aqgy / video 两类都出现过），所以不做检测，全部一刀切。
iemocap  360x480 的画面四周都是黑边，有效区只占七成，人物太小 ——
         按固定参数裁掉黑边。该库录制格式统一，采样 8 条参数一致。

只动 visual.mp4：完整视频模态本来就给声音，字幕算不上泄漏，
而且重编码一次就掉一次画质，能不动的不动。
原件备份到 out/visual-backup/，可随时还原。

裁剪必须重编码（流拷贝改不了画面），因此逐条核对**帧数**一帧不差——
四个模态共用一条时间轴，视觉轨少了帧，标注曲线就对不上。

不按容器时长校验：约 2% 的片源容器里写的时长比实际能解码的帧长
（chsims 尤甚，最多虚报 0.16 秒）。原来的流拷贝把这个虚报的时长一起抄了过来，
重编码才让它现形。帧数才是真正守恒的量。
"""

import argparse
import json
import sys
import shutil
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from datapaths import MEDIA_DIR  # noqa: E402

ROOT = MEDIA_DIR
MEDIA = ROOT / "out" / "media"
BACKUP = ROOT / "out" / "visual-backup"

# 下缘裁掉 18%：抽查的字幕顶边在 88% 处，留 6 个百分点的余量。
CHSIMS_KEEP = 0.82
# 采样 8 条 cropdetect 都落在 crop=346..350:238:6..8:122，取交集再内缩 2px。
IEMOCAP_CROP = "crop=344:236:8:123"


def crop_filter(sample_id: str, width: int, height: int) -> str | None:
    if sample_id.startswith("chsims_"):
        keep = int(height * CHSIMS_KEEP) // 2 * 2
        return f"crop={width}:{keep}:0:0"
    if sample_id.startswith("iemocap_"):
        # 参数是按 360x480 定的，换了尺寸就不能套用
        return IEMOCAP_CROP if (width, height) == (360, 480) else None
    return None


def probe(path: Path) -> tuple[int, int, float]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:format=duration",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    data = json.loads(out)
    stream = data["streams"][0]
    return stream["width"], stream["height"], float(data["format"]["duration"])


def count_frames(path: Path) -> int:
    """实际能解码出多少帧。容器头里的时长不可信，这个才是。"""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip().rstrip(",")
    return int(out)


def process(sample_id: str) -> dict:
    visual = MEDIA / sample_id / "visual.mp4"
    record = {"sample_id": sample_id, "status": "ok"}
    try:
        width, height, duration = probe(visual)
        crop = crop_filter(sample_id, width, height)
        if crop is None:
            return {**record, "status": "skipped", "reason": f"{width}x{height}"}

        backup = BACKUP / sample_id / "visual.mp4"
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copyfile(visual, backup)

        tmp = visual.with_suffix(".tmp.mp4")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(backup),
             "-vf", crop, "-an",
             "-c:v", "libx264", "-crf", "20", "-preset", "veryfast",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(tmp)],
            check=True, capture_output=True, text=True,
        )

        new_w, new_h, new_duration = probe(tmp)
        frames_in, frames_out = count_frames(backup), count_frames(tmp)
        if frames_in != frames_out:
            tmp.unlink(missing_ok=True)
            return {**record, "status": "failed",
                    "reason": f"丢帧 {frames_in} -> {frames_out}"}
        tmp.replace(visual)
        return {**record, "crop": crop, "frames": frames_out,
                "size": f"{width}x{height} -> {new_w}x{new_h}",
                "duration": round(new_duration, 3),
                # 容器虚报时长的片源，重编码后时长会缩到真实长度
                "duration_was": round(duration, 3)}
    except subprocess.CalledProcessError as error:
        return {**record, "status": "failed", "reason": (error.stderr or "")[-300:]}
    except Exception as error:  # noqa: BLE001 - 单条失败不该拖垮整批
        return {**record, "status": "failed", "reason": repr(error)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条，用于试跑")
    parser.add_argument("--only", help="只跑这个文件里列出的样本编号（每行一个）")
    parser.add_argument("--out", default=str(ROOT / "out" / "recrop.jsonl"))
    args = parser.parse_args()

    samples = sorted(
        d.name for d in MEDIA.iterdir()
        if d.is_dir() and d.name.split("_")[0] in {"chsims", "iemocap"}
    )
    if args.only:
        wanted = {
            line.strip()
            for line in Path(args.only).read_text("utf-8").splitlines()
            if line.strip()
        }
        missing = wanted - set(samples)
        if missing:
            raise SystemExit(f"这些样本不在 media 目录里：{sorted(missing)[:5]}")
        samples = [s for s in samples if s in wanted]
    if args.limit:
        samples = samples[: args.limit]
    print(f"待处理 {len(samples)} 条", flush=True)

    counts: dict[str, int] = {}
    with open(args.out, "w", encoding="utf-8") as sink, \
            ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i, record in enumerate(pool.map(process, samples, chunksize=4), 1):
            sink.write(json.dumps(record, ensure_ascii=False) + "\n")
            counts[record["status"]] = counts.get(record["status"], 0) + 1
            if i % 200 == 0:
                print(f"  {i}/{len(samples)}  {counts}", flush=True)

    print(f"完成 {counts}", flush=True)
    # 只要有一条没成，退出码就不为 0：上一次批处理曾经在全部失败时报成功
    if counts.get("failed"):
        raise SystemExit(f"有 {counts['failed']} 条失败，见 {args.out}")


if __name__ == "__main__":
    main()
