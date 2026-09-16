"""挑一批样本、内嵌音频，供人工听审对齐结果。"""
from datapaths import ALIGN_DIR  # noqa: E402
OUT_DIR = ALIGN_DIR / "out"
import base64, json, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from datapaths import stage_path

sys.path.insert(0, str(stage_path("speaker-frames")))
from align import audio_source
from resolve import resolve

rows = [json.loads(l) for l in open(OUT_DIR / "pilot.jsonl")]
ok = [r for r in rows if r["status"] == "ok"]

chosen_ids = {r["sample_id"] for r in ok if r["silent_tail"] >= 0.8}
chosen_ids |= {r["sample_id"] for r in ok if r["in_speech"] < 0.9}
for src in ("meld", "mustard", "iemocap", "mosi"):
    pool = [r for r in ok if r["source"] == src and r["sample_id"] not in chosen_ids]
    chosen_ids |= {r["sample_id"] for r in pool[:3]}

out = []
for r in [r for r in ok if r["sample_id"] in chosen_ids]:
    info = resolve(r["sample_id"], r["source"])
    with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as tmp:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(audio_source(info["video_path"])),
             "-ac", "1", "-ar", "16000", "-c:a", "aac", "-b:a", "32k", tmp.name],
            check=True)
        blob = Path(tmp.name).read_bytes()
    Path(tmp.name).unlink()
    item = dict(r)
    item["audio"] = "data:audio/mp4;base64," + base64.b64encode(blob).decode()
    item["kind"] = ("laugh" if r["silent_tail"] >= 0.8
                    else "suspect" if r["in_speech"] < 0.9 else "normal")
    out.append(item)

out.sort(key=lambda r: ({"laugh": 0, "suspect": 1, "normal": 2}[r["kind"]], -r["silent_tail"]))
(OUT_DIR / "review_data.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
counts = {k: sum(1 for r in out if r["kind"] == k) for k in ("laugh", "suspect", "normal")}
print(f"选中 {len(out)} 条 {counts}")
print(f"内嵌音频合计 {sum(len(r['audio']) for r in out)/1024/1024:.1f} MB")
