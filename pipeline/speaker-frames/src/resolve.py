"""sample_id -> 视频路径 + 说话人元数据 的统一解析器。"""
import csv, json, os, re, sys
from pathlib import Path

DATASETS = Path("/scratch/project_2017416/yyy2026/datasets")
MELD_VIDEO_DIR = Path("/scratch/project_2007389/yyy/MELD.Raw/train_splits")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from datapaths import POOL_DATA  # noqa: E402

POOL = POOL_DATA / "annotation_pool_3500.jsonl"

_cache = {}


def _meld_index():
    if "meld" not in _cache:
        idx = {}
        with open(DATASETS / "MELD/train_sent_emo.csv", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                idx[f"dia{row['Dialogue_ID']}_utt{row['Utterance_ID']}"] = row
        _cache["meld"] = idx
    return _cache["meld"]


def _mustard_index():
    if "mustard" not in _cache:
        with open(DATASETS / "MUStARD/sarcasm_data.json", encoding="utf-8") as f:
            _cache["mustard"] = json.load(f)
    return _cache["mustard"]


def _interface_index(key, rel):
    if key not in _cache:
        idx = {}
        with open(DATASETS / rel, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                idx[row["id"]] = row
        _cache[key] = idx
    return _cache[key]


def _chsims_index():
    """clip_id 可能带 _0/_1 后缀，故以 interface.csv 为准建 {video_id}_{clip_id} 索引。"""
    if "chsims" not in _cache:
        idx = {}
        with open(DATASETS / "CH-SIMS/ch-simsv2s/ch-sims-interface.csv",
                  newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                idx[f"{row['video_id']}_{row['clip_id']}"] = row
        _cache["chsims"] = idx
    return _cache["chsims"]


def resolve(sample_id, source):
    """返回 dict: video_path, speaker_name, gender, extra。video_path 可能不存在。"""
    key = sample_id[len(source) + 1:]
    if source == "meld":
        m = re.fullmatch(r"dia(\d+)_utt(\d+)", key)
        if not m:
            return None
        row = _meld_index().get(key) or {}
        return {"video_path": MELD_VIDEO_DIR / f"{key}.mp4",
                "speaker_name": row.get("Speaker"),
                "gender": None,
                "extra": {"text": row.get("Utterance") or ""}}
    if source == "mustard":
        meta = _mustard_index().get(key)
        return {"video_path": DATASETS / f"MUStARD/new_data/{key}/video.mp4",
                "speaker_name": (meta or {}).get("speaker"),
                "gender": None,
                "extra": {"show": (meta or {}).get("show"),
                          "text": (meta or {}).get("utterance") or ""}}
    if source == "chsims":
        row = _chsims_index().get(key)
        if row is None:
            return None
        return {"video_path": Path(row["Interface"]),
                "speaker_name": None, "gender": None,
                "extra": {"video_id": row["video_id"], "clip_id": row["clip_id"],
                          "text": row["text"]}}
    if source == "mosi":
        row = _interface_index("mosi", "CMU-MOSI/mosi_interface.csv").get(key) or {}
        path = row.get("video_path")
        return {"video_path": Path(path) if path else DATASETS / f"CMU-MOSI/Video-Segmented/{key}.mp4",
                "speaker_name": None, "gender": None,
                "extra": {"youtube_id": key.rsplit("_", 1)[0],
                          "text": row.get("transcription") or ""}}
    if source == "iemocap":
        row = _interface_index("iemocap", "iemocap-clip/iemocap_interface.csv").get(key) or {}
        path = row.get("video_path")
        m = re.fullmatch(r"(Ses\d+[FM])_(.+)_([FM])(\d+)", key)
        session, gender = (m.group(1), m.group(3)) if m else (None, None)
        return {"video_path": Path(path) if path else DATASETS / f"iemocap-clip/clips/{key}.mp4",
                "speaker_name": None, "gender": gender,
                "extra": {"session": session,
                          "dialog": f"{session}_{m.group(2)}" if m else None,
                          "text": row.get("transcription") or ""}}
    return None


def load_pool():
    with open(POOL, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            yield d["sample_id"], d["source"]
