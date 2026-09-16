"""公共工具：路径常量、JSONL 断点读写、人脸质量打分、裁切。"""
import json, math, os, sys, threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from datapaths import FRAMES_DIR  # noqa: E402

# 代码在仓库里，数据在 scratch 上——两者由 datapaths 接起来
ROOT = FRAMES_DIR
OUT = ROOT / "out"
FRAMES = OUT / "frames"
REVIEW = OUT / "review"
MANIFEST = OUT / "manifest.jsonl"
FACESCAN = OUT / "facescan.jsonl"
YUNET = ROOT / "models/face_detection_yunet_2023mar.onnx"

SCAN_FRAMES = 9          # 每条视频扫描的帧数
CROP_MARGIN = 0.6        # 人脸框外扩比例（上下左右按框宽高的比例）
CROP_SIZE = 512          # 输出图边长


def ensure_dirs():
    for d in (OUT, FRAMES, REVIEW):
        d.mkdir(parents=True, exist_ok=True)


def load_done(path, key="sample_id"):
    """读已完成记录，返回 {key: record}。用于断点续跑。"""
    done = {}
    if not Path(path).exists():
        return done
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue          # 上次中断写了半行，丢弃
            done[rec[key]] = rec
    return done


class JsonlWriter:
    """追加写 JSONL，每行 flush + fsync，保证中断后不丢已完成项。"""

    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._f = open(path, "a", encoding="utf-8")
        self._lock = threading.Lock()

    def write(self, rec):
        with self._lock:
            self._f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._f.flush()
            os.fsync(self._f.fileno())

    def close(self):
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def face_score(face, frame_w, frame_h):
    """人脸可辨识度打分：面积为主，居中与正脸（双眼水平对称）为辅。

    face: YuNet 输出的 15 维向量 [x, y, w, h, 右眼x,y, 左眼x,y, 鼻x,y, 右嘴x,y, 左嘴x,y, score]
    """
    x, y, w, h = (float(v) for v in face[:4])
    conf = float(face[14])
    area = (w * h) / (frame_w * frame_h)

    cx, cy = x + w / 2, y + h / 2
    off = math.hypot(cx / frame_w - 0.5, cy / frame_h - 0.5) / 0.707
    center = 1.0 - off

    # 正脸程度：鼻子应落在双眼中点附近，且双眼连线接近水平
    rex, rey, lex, ley, nx, ny = (float(v) for v in face[4:10])
    eye_dx, eye_dy = lex - rex, ley - rey
    eye_d = math.hypot(eye_dx, eye_dy) + 1e-6
    yaw = abs((nx - (rex + lex) / 2) / eye_d)        # 0=正脸，越大越侧
    roll = abs(eye_dy / eye_d)
    frontal = max(0.0, 1.0 - yaw * 1.4 - roll * 0.8)

    return float((0.55 * math.sqrt(area) * 3.0 + 0.15 * center + 0.30 * frontal) * conf)


def sharpness(img):
    """拉普拉斯方差，衡量清晰度（越大越锐）。"""
    import cv2
    return float(cv2.Laplacian(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())


def crop_face(frame, bbox, margin=CROP_MARGIN, size=CROP_SIZE):
    """按 bbox 外扩裁切为正方形；越界处用边缘复制填充，保证人脸始终居中。"""
    import cv2
    import numpy as np
    x, y, w, h = bbox
    cx, cy = x + w / 2, y + h / 2
    side = max(w, h) * (1 + 2 * margin)
    x0, y0 = int(round(cx - side / 2)), int(round(cy - side / 2))
    x1, y1 = int(round(cx + side / 2)), int(round(cy + side / 2))

    H, W = frame.shape[:2]
    pad_l, pad_t = max(0, -x0), max(0, -y0)
    pad_r, pad_b = max(0, x1 - W), max(0, y1 - H)
    if pad_l or pad_t or pad_r or pad_b:
        frame = cv2.copyMakeBorder(frame, pad_t, pad_b, pad_l, pad_r, cv2.BORDER_REPLICATE)
        x0 += pad_l; x1 += pad_l; y0 += pad_t; y1 += pad_t
    return cv2.resize(frame[y0:y1, x0:x1], (size, size), interpolation=cv2.INTER_AREA)


MIN_FACE_H_RATIO = 0.07      # 人脸高度至少占画面高度的比例
MIN_REL_AREA = 0.20          # 面积至少是画面内最大脸的这个比例
MIN_DET = 0.70               # 检测置信度下限


def main_faces(faces, frame_h):
    """滤掉背景路人：过小、过暗淡、相对最大脸太小的框都不算候选说话人。"""
    cand = [f for f in faces if f["det"] >= MIN_DET and f["bbox"][3] >= MIN_FACE_H_RATIO * frame_h]
    if not cand:
        return []
    amax = max(f["bbox"][2] * f["bbox"][3] for f in cand)
    return [f for f in cand if f["bbox"][2] * f["bbox"][3] >= MIN_REL_AREA * amax]


def count_main(faces, frame_h):
    return len(main_faces(faces, frame_h))


def faces_for_pick(faces, frame_h):
    """选帧阶段的候选脸：比 main_faces 宽松一档的兜底。

    main_faces 的尺寸与置信度门限是为「分桶」定的，宁严勿松；
    但到了选帧阶段，严格过滤后一张不剩就只能判 failed 了——
    实测这类样本要么是远景全身（脸小于尺寸门限），要么是侧躺/大角度侧脸
    （检测置信度偏低），画面里其实有人。有一张能认的脸总比没有强，
    这种兜底出来的结果由调用方标成 needs_review。
    """
    cand = main_faces(faces, frame_h)
    if cand:
        return cand, False
    loose = [f for f in faces if f["det"] >= 0.40]
    if not loose:
        return [], True
    return [max(loose, key=lambda f: f["bbox"][2] * f["bbox"][3])], True
