"""素材预处理：为每个样本产出四个模态的播放素材与转录稿。

产出（相对 out/）：
    media/<sample_id>/visual.mp4       去掉音轨的视频
    media/<sample_id>/audio.m4a        双声道音频
    media/<sample_id>/audiovisual.mp4  视频 + 双声道音频
    media/<sample_id>/speaker.jpg      说话人静帧（取自 06 交付）
    transcripts/<sample_id>.json       词级时间戳

两处必须特殊处理，直接套通用命令会出错：
    MELD     音轨是 5.1 六声道，不下混浏览器放不出声
    MUStARD  video.mp4 **没有音轨**，声音在同目录的 audio.wav，要手动合入

视频一律**流拷贝**不重编码：源本来就是 h264，重编码既慢又掉画质。
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from datapaths import ALIGN_DIR, FRAMES_DIR, stage_path  # noqa: E402

sys.path.insert(0, str(stage_path("speaker-frames")))

import transcript as tx  # noqa: E402
from resolve import resolve  # noqa: E402

FRAMES = FRAMES_DIR / "out"
ALIGN = ALIGN_DIR / "out" / "align"


def run(args: list[str]) -> None:
    subprocess.run(args, check=True, capture_output=True)


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return round(float(out), 3)


def build_media(sample_id: str, source: str, video: Path, out_dir: Path) -> float:
    out_dir.mkdir(parents=True, exist_ok=True)
    visual = out_dir / "visual.mp4"
    audio = out_dir / "audio.m4a"
    audiovisual = out_dir / "audiovisual.mp4"

    # MUStARD 的声音是独立文件；其余源的音轨就在视频里
    sidecar = video.with_name("audio.wav")
    external_audio = sidecar if sidecar.exists() else None

    run(["ffmpeg", "-v", "error", "-y", "-i", str(video),
         "-map", "0:v:0", "-c:v", "copy", "-an", str(visual)])

    audio_input = ["-i", str(external_audio or video)]
    run(["ffmpeg", "-v", "error", "-y", *audio_input,
         "-map", "0:a:0", "-ac", "2", "-c:a", "aac", "-b:a", "96k", str(audio)])

    if external_audio:
        run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(external_audio),
             "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
             "-ac", "2", "-c:a", "aac", "-b:a", "96k", "-shortest", str(audiovisual)])
    else:
        run(["ffmpeg", "-v", "error", "-y", "-i", str(video),
             "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
             "-ac", "2", "-c:a", "aac", "-b:a", "96k", str(audiovisual)])

    frame = FRAMES / "frames" / f"{sample_id}.jpg"
    if frame.exists():
        shutil.copyfile(frame, out_dir / "speaker.jpg")

    # 四个模态共用同一条时间轴，时长以合成后的完整视频为准
    return probe_duration(audiovisual)


def load_alignment() -> dict[str, dict]:
    rows = {}
    for shard in sorted(ALIGN.glob("shard-*.jsonl")):
        for line in shard.open(encoding="utf-8"):
            record = json.loads(line)
            rows[record["sample_id"]] = record
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(MEDIA_DIR / "out"))
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--of", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    delivery = [
        json.loads(line)
        for line in (FRAMES / "manifest.jsonl").open(encoding="utf-8")
    ]
    alignment = load_alignment()

    out_root = Path(args.out)
    (out_root / "transcripts").mkdir(parents=True, exist_ok=True)
    report_path = out_root / f"prepared-{args.shard:02d}.jsonl"

    done = set()
    if report_path.exists():
        for line in report_path.open(encoding="utf-8"):
            done.add(json.loads(line)["sample_id"])

    todo = [r for i, r in enumerate(delivery) if i % args.of == args.shard]
    if args.limit:
        todo = todo[: args.limit]

    written = 0
    with report_path.open("a", encoding="utf-8") as handle:
        for row in todo:
            sample_id = row["sample_id"]
            if sample_id in done:
                continue
            record = {"sample_id": sample_id, "source": row["source"]}
            try:
                info = resolve(sample_id, row["source"])
                duration = build_media(
                    sample_id, row["source"], info["video_path"],
                    out_root / "media" / sample_id,
                )
                aligned = alignment.get(sample_id)
                if not aligned or aligned["status"] != "ok":
                    raise ValueError("缺少对齐结果")
                doc = tx.build(aligned["words"], duration)
                tx.validate(doc, duration)
                (out_root / "transcripts" / f"{sample_id}.json").write_text(
                    json.dumps(doc, ensure_ascii=False), encoding="utf-8"
                )
                record |= {
                    "status": "ok",
                    "duration": duration,
                    "speaker_name": row.get("speaker_name"),
                    "text": aligned["text"],
                }
            except Exception as error:
                record |= {"status": "failed",
                           "error": f"{type(error).__name__}: {error}"}
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            written += 1
            if written % 50 == 0:
                print(f"[shard {args.shard}] {written}/{len(todo)}", flush=True)

    print(f"[shard {args.shard}] 完成，本次 {written}", flush=True)


if __name__ == "__main__":
    main()
