"""人脸轨迹的纯函数核心：链接、补洞、平滑、判级。

这里刻意不 import cv2，也不碰文件系统——全部是可单测的纯计算。
检测与读写在 `track.py`，两者的接缝是「每帧候选脸列表」这一种数据结构：

    frames_cands[i] = [{"bbox": [x, y, w, h], "det": 0.98, "sim": 0.71}, ...]

`sim` 是该候选脸与说话人身份模板的 SFace 余弦相似度，由调用方算好传进来。
"""

# ---- 阈值：改这里，不要散落到各处 ----

SIM_ACCEPT = 0.25
"""单帧接受候选脸的相似度下限。

刻意低于 SFace 官方同人阈值 0.363——侧脸、运动模糊、低光会让单帧相似度
掉到 0.3 以下，按 0.363 卡会打出一堆假空洞。身份是否可信改由
`evaluate()` 用轨迹的**平均**相似度把关，那才是统计上有意义的量。
"""

IOU_BONUS = 0.30
"""时序连贯性奖励权重。

多人同框时（iemocap 双人），只看相似度会在两张脸之间来回跳。
加一项与上一帧已接受框的 IoU，让轨迹倾向于跟住同一个人。
"""

MIN_DET = 0.70
MIN_FACE_H_RATIO = 0.07
"""与 speaker-frames/common.py 同口径，避免两处标准打架。"""

MEDIAN_WIN = 5
EMA_ALPHA = 0.40
"""平滑参数。中值窗压脉冲跳变，EMA 压高频抖动。

不平滑的话裁剪框会逐帧跟着检测噪声跳，标注者看到的画面持续抖动，
注意力会被抖动本身带跑，直接污染 arousal——所以这步不是可选项。
"""

# ---- 判级阈值 ----
MIN_DET_RATE = 0.60
MAX_GAP_SECONDS = 0.5
MIN_MEAN_SIM = 0.363          # SFace 官方同人阈值
MIN_MEAN_FACE_H_RATIO = 0.07


def iou(a, b):
    """两个 [x, y, w, h] 框的交并比。"""
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    ax1, ay1 = ax0 + aw, ay0 + ah
    bx1, by1 = bx0 + bw, by0 + bh
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def filter_candidates(faces, frame_h):
    """滤掉背景路人：置信度过低、脸太小的都不算候选说话人。"""
    return [
        f for f in faces
        if f["det"] >= MIN_DET and f["bbox"][3] >= MIN_FACE_H_RATIO * frame_h
    ]


def link_track(frames_cands, frame_h):
    """把逐帧候选链接成一条轨迹。

    返回长度与输入相同的列表，每项是 dict 或 None（该帧没跟上）。
    选择依据是 `sim + IOU_BONUS * IoU(上一帧已接受框)`——相似度定身份，
    IoU 定连贯，后者让多人同框时不会在两张脸之间来回跳。
    """
    track = [None] * len(frames_cands)
    prev = None
    for i, faces in enumerate(frames_cands):
        cands = filter_candidates(faces, frame_h)
        if not cands:
            continue
        best, best_score = None, None
        for f in cands:
            score = f["sim"]
            if prev is not None:
                score += IOU_BONUS * iou(f["bbox"], prev)
            if best_score is None or score > best_score:
                best, best_score = f, score
        if best["sim"] < SIM_ACCEPT:
            continue          # 跟丢了，留给 fill_gaps 补
        track[i] = {
            "bbox": [float(v) for v in best["bbox"]],
            "det": float(best["det"]),
            "sim": float(best["sim"]),
            "src": "det",
        }
        prev = track[i]["bbox"]
    return track


def gaps(track):
    """返回所有空洞的 (起, 止) 闭区间下标。"""
    out = []
    start = None
    for i, t in enumerate(track):
        if t is None and start is None:
            start = i
        elif t is not None and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(track) - 1))
    return out


def max_gap(track):
    return max((b - a + 1 for a, b in gaps(track)), default=0)


def fill_gaps(track):
    """线性插值补洞；首尾的空洞用最近的已知框外推（保持不动）。

    补出来的项标 `src="interp"`，这样 A3 人工审核时一眼能看出哪些帧是猜的。
    原地修改并返回同一个列表。
    """
    known = [i for i, t in enumerate(track) if t is not None]
    if not known:
        return track
    for a, b in gaps(track):
        left = a - 1 if a - 1 >= 0 and track[a - 1] is not None else None
        right = b + 1 if b + 1 < len(track) and track[b + 1] is not None else None
        for i in range(a, b + 1):
            if left is None and right is None:
                continue
            if left is None:
                box = list(track[right]["bbox"])
            elif right is None:
                box = list(track[left]["bbox"])
            else:
                span = right - left
                w = (i - left) / span
                box = [
                    track[left]["bbox"][k] * (1 - w) + track[right]["bbox"][k] * w
                    for k in range(4)
                ]
            track[i] = {"bbox": box, "det": 0.0, "sim": 0.0, "src": "interp"}
    return track


def _median(vals):
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def smooth(track, median_win=MEDIAN_WIN, ema_alpha=EMA_ALPHA):
    """中值滤波压脉冲，再单向 EMA 压高频抖动。

    只动 bbox，不动 det / sim / src——后者是溯源信息，平滑掉就查不出问题了。
    """
    boxes = [t["bbox"] for t in track if t is not None]
    if len(boxes) < 2:
        return track
    idx = [i for i, t in enumerate(track) if t is not None]
    half = median_win // 2
    med = []
    for pos in range(len(idx)):
        lo, hi = max(0, pos - half), min(len(idx), pos + half + 1)
        window = [boxes[p] for p in range(lo, hi)]
        med.append([_median([w[k] for w in window]) for k in range(4)])
    ema = list(med[0])
    for pos, box in enumerate(med):
        ema = [ema_alpha * box[k] + (1 - ema_alpha) * ema[k] for k in range(4)]
        track[idx[pos]]["bbox"] = list(ema)
    return track


def evaluate(track, fps, frame_h):
    """算统计量并判级。

    判据命中一条标 low_confidence，两条以上标 drop；**不自动删**，
    由 A3 的人工审核决定去留。
    """
    n = len(track)
    det = [t for t in track if t is not None and t["src"] == "det"]
    interp = [t for t in track if t is not None and t["src"] == "interp"]
    missing = n - len(det) - len(interp)
    det_rate = len(det) / n if n else 0.0
    mean_sim = sum(t["sim"] for t in det) / len(det) if det else 0.0
    heights = [t["bbox"][3] for t in track if t is not None]
    mean_h_ratio = (sum(heights) / len(heights) / frame_h) if heights and frame_h else 0.0

    # 空洞按补洞前的口径算：src != "det" 的连续段
    pseudo = [None if (t is None or t["src"] != "det") else t for t in track]
    gap_frames = max_gap(pseudo)
    gap_seconds = gap_frames / fps if fps else 0.0

    reasons = []
    if det_rate < MIN_DET_RATE:
        reasons.append(f"det_rate={det_rate:.2f}<{MIN_DET_RATE}")
    if gap_seconds > MAX_GAP_SECONDS:
        reasons.append(f"max_gap={gap_seconds:.2f}s>{MAX_GAP_SECONDS}s")
    if mean_sim < MIN_MEAN_SIM:
        reasons.append(f"mean_sim={mean_sim:.3f}<{MIN_MEAN_SIM}")
    if mean_h_ratio < MIN_MEAN_FACE_H_RATIO:
        reasons.append(f"face_h={mean_h_ratio:.3f}<{MIN_MEAN_FACE_H_RATIO}")

    status = "ok" if not reasons else ("drop" if len(reasons) >= 2 else "low_confidence")
    stats = {
        "detected": len(det),
        "interpolated": len(interp),
        "missing": missing,
        "max_gap_frames": gap_frames,
        "max_gap_seconds": round(gap_seconds, 3),
        "det_rate": round(det_rate, 4),
        "mean_sim": round(mean_sim, 4),
        "mean_face_h_ratio": round(mean_h_ratio, 4),
    }
    return stats, status, reasons


def build(frames_cands, fps, frame_h):
    """完整流水：链接 → 补洞 → 平滑 → 判级。"""
    track = link_track(frames_cands, frame_h)
    stats, status, reasons = evaluate(fill_gaps(track), fps, frame_h)
    smooth(track)
    return track, stats, status, reasons
