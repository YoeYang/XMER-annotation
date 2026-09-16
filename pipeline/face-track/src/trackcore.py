"""人脸裁剪框的纯函数核心：认人、算稳定框、判级。

这里刻意不 import cv2，也不碰文件系统——全部是可单测的纯计算。
检测与读写在 `track.py`，两者的接缝是「每帧候选脸列表」这一种数据结构：

    frames_cands[i] = [{"bbox": [x, y, w, h], "det": 0.98, "sim": 0.71}, ...]

`sim` 是该候选脸与说话人身份模板的 SFace 余弦相似度，由调用方算好传进来。

**设计要点：不追求逐帧跟准。** 侧脸、低头、运动模糊检不出人脸是常态，
不是样本有问题。所以这里算的是一个**固定尺寸、慢速平移**的裁剪框：
检不出的帧框留在原处，画面照常播真实帧——而不是冻结画面糊弄标注者。
固定尺寸同时消掉了缩放抖动。
"""

# ---- 认人 ----

SIM_ACCEPT = 0.25
"""单帧接受候选脸的相似度下限。

刻意低于 SFace 官方同人阈值 0.363——侧脸、运动模糊、低光会让单帧相似度
掉到 0.3 以下。身份是否可信改由 `evaluate()` 用轨迹的**平均**相似度把关，
那才是统计上有意义的量。
"""

IOU_BONUS = 0.30
"""时序连贯性奖励权重。

多人同框时（iemocap 双人），只看相似度会在两张脸之间来回跳。
加一项与上一帧已接受框的 IoU，让轨迹倾向于跟住同一个人。
"""

MIN_DET = 0.70
MIN_FACE_H_RATIO = 0.07
"""与 speaker-frames/common.py 同口径，避免两处标准打架。"""

# ---- 裁剪框 ----

CROP_MARGIN = 0.20
"""框在人脸外扩的比例。

比 speaker-frames 静帧用的 0.6 收得多——静帧是给人核对身份的，留白无所谓；
这里是给标注者看表情的，**脸要尽量占满画面**。

0.20 是在试点 50 条上扫出来的，不是拍脑袋（见 `coverage()`）：

    margin   脸完整在框内   脸占框面积   覆盖<95%的样本
     0.60       99.4%        13.7%          1
     0.25       98.9%        29.1%          4
     0.20       98.7%        33.4%          5
     0.15       97.9%        38.7%         11   <- 拐点，明显劣化

取 0.20：脸占的面积是原来 0.6 的 2.4 倍，覆盖率只掉 0.7 个百分点。
"""

SIZE_PCTL = 0.90
"""框边长取检出帧人脸尺寸的这个分位。

取高分位而不是中位：宁可框大一点留白，也不能在人脸忽然凑近时切掉半张脸。
"""

CENTER_EMA = 0.15
"""中心平移的 EMA 系数，取得很小 —— 要的就是「慢」。"""

STATIC_RATIO = 0.10
"""中心位移范围小于框边长的这个比例时，直接退化成全段静态框。"""

# ---- 判级 ----

MIN_DET_RATE = 0.30
"""检出率门槛。

认不出目标说话人的帧一律输出**黑屏**（而不是把镜头里的另一个人给标注者看），
所以这条门槛等价于「黑屏不超过 70%」——Yoe 定的口径。
"""

LOW_DET_RATE = 0.50
"""落在 [MIN_DET_RATE, LOW_DET_RATE) 的标 low_confidence，供人工优先审核。
黑屏过半虽然还能标，但值得先看一眼。"""

MIN_MEAN_SIM = 0.363
"""SFace 官方同人阈值。低于它说明整条跟错了人，不是「检不出」而是「认错」。"""

# ---- 可见性迟滞（防屏闪）----

HOLD_SECONDS = 0.40
"""丢失短于这个时长就当人还在，继续显示画面。

侧脸、低头、运动模糊会让检测一帧有一帧无。若逐帧照搬，画面就在
「真实帧 / 黑屏」之间高频交替，**看着像屏闪，眼睛很痛**。
而短暂丢失时人其实还在原处（框是稳定的），显示出来的内容是对的。
只有连续丢失够久，才说明镜头真的切走了。
"""

MIN_VISIBLE_SECONDS = 0.20
"""可见段短于这个时长就抹掉，当作不可见。

切走的镜头中间偶尔蒙对一帧，会在黑屏里闪一下白——同样刺眼。
"""


def smooth_presence(present, fps):
    """把逐帧检出标记整成不闪的可见标记。

    形态学的闭运算 + 开运算：先填短丢失（闭），再去短可见（开）。
    顺序不能反——先开会把本来要被填上的零星检出先删掉。
    """
    if not present:
        return []
    hold = max(1, int(round(HOLD_SECONDS * fps)))
    keep = max(1, int(round(MIN_VISIBLE_SECONDS * fps)))
    vis = list(present)

    for a, b in _runs(vis, 0):
        # 首尾的丢失不填：开头还没出现过人，结尾已经走了
        if a > 0 and b < len(vis) - 1 and (b - a + 1) <= hold:
            for i in range(a, b + 1):
                vis[i] = 1
    for a, b in _runs(vis, 1):
        if (b - a + 1) < keep:
            for i in range(a, b + 1):
                vis[i] = 0
    return vis


def _runs(seq, value):
    """返回 seq 中所有等于 value 的连续段 (起, 止)。"""
    out, start = [], None
    for i, v in enumerate(seq):
        if v == value and start is None:
            start = i
        elif v != value and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(seq) - 1))
    return out


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

    返回长度与输入相同的列表，每项是 dict 或 None（该帧没认出目标人脸）。
    选择依据是 `sim + IOU_BONUS * IoU(上一帧已接受框)`——相似度定身份，
    IoU 定连贯，后者让多人同框时不会在两张脸之间来回跳。

    **None 不代表样本有问题**，只代表这一帧没检出；后面算框时会跳过它。
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
            continue
        track[i] = {
            "bbox": [float(v) for v in best["bbox"]],
            "det": float(best["det"]),
            "sim": float(best["sim"]),
        }
        prev = track[i]["bbox"]
    return track


def gaps(track):
    """返回所有未检出段的 (起, 止) 闭区间下标。只用于报告，不用于判级。"""
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


def _percentile(vals, p):
    s = sorted(vals)
    if not s:
        return 0.0
    return s[min(len(s) - 1, int(round(p * (len(s) - 1))))]


def _median(vals):
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def _interp_centers(track):
    """检出帧取人脸中心，未检出帧线性插值；首尾未检出则保持最近的已知中心。

    框大且移动慢，插值误差无所谓——这正是「不追求逐帧跟准」的地方。
    """
    known = [(i, (t["bbox"][0] + t["bbox"][2] / 2, t["bbox"][1] + t["bbox"][3] / 2))
             for i, t in enumerate(track) if t is not None]
    if not known:
        return None
    centers = [None] * len(track)
    for i, c in known:
        centers[i] = c
    first, last = known[0][0], known[-1][0]
    for i in range(first):
        centers[i] = known[0][1]
    for i in range(last + 1, len(track)):
        centers[i] = known[-1][1]
    k = 0
    for i in range(first, last + 1):
        if centers[i] is not None:
            continue
        while known[k + 1][0] < i:
            k += 1
        (ia, ca), (ib, cb) = known[k], known[k + 1]
        w = (i - ia) / (ib - ia)
        centers[i] = (ca[0] * (1 - w) + cb[0] * w, ca[1] * (1 - w) + cb[1] * w)
    return centers


def stable_box(track, frame_w, frame_h, fps, margin=CROP_MARGIN):
    """算固定尺寸、慢速平移的裁剪框。

    返回 (mode, side, centers)：
      mode    "static" 全段一动不动 / "slow" 慢速平移
      side    正方形边长，全段不变——固定尺寸天然没有缩放抖动
      centers 每帧的 (cx, cy)，已钳在画面内保证框不越界

    没有任何一帧认出人脸时返回 (None, 0.0, None)。
    """
    dets = [t for t in track if t is not None]
    if not dets:
        return None, 0.0, None

    face = _percentile([max(t["bbox"][2], t["bbox"][3]) for t in dets], SIZE_PCTL)
    side = face * (1 + 2 * margin)
    side = min(side, float(min(frame_w, frame_h)))

    centers = _interp_centers(track)

    # 大窗中值压掉零星跳变，窗口按秒取而不是按帧——素材帧率不一定都是 25
    win = max(3, int(round(fps * 0.8)) | 1)
    half = win // 2
    med = []
    for i in range(len(centers)):
        lo, hi = max(0, i - half), min(len(centers), i + half + 1)
        med.append((_median([centers[j][0] for j in range(lo, hi)]),
                    _median([centers[j][1] for j in range(lo, hi)])))

    # 位移够小就别动了，静态框最省心也最不打扰人
    span = max(max(c[0] for c in med) - min(c[0] for c in med),
               max(c[1] for c in med) - min(c[1] for c in med))
    if span < side * STATIC_RATIO:
        cx, cy = _median([c[0] for c in med]), _median([c[1] for c in med])
        out = [_clamp(cx, cy, side, frame_w, frame_h)] * len(med)
        return "static", side, out

    ema = list(med[0])
    out = []
    for c in med:
        ema = [CENTER_EMA * c[k] + (1 - CENTER_EMA) * ema[k] for k in range(2)]
        out.append(_clamp(ema[0], ema[1], side, frame_w, frame_h))
    return "slow", side, out


def _clamp(cx, cy, side, frame_w, frame_h):
    """把中心钳进画面，保证边长 side 的框整个落在画面内。"""
    half = side / 2
    cx = min(max(cx, half), max(half, frame_w - half))
    cy = min(max(cy, half), max(half, frame_h - half))
    return (cx, cy)


def evaluate(track, fps, frame_h):
    """算统计量并判级。

    只有两条判据：
      * 检出率 < 0.30 —— 黑屏超过七成，这条做不了 face/body
      * 平均相似度 < 0.363 —— 整条跟错了人（不是「检不出」，是「认错」）

    **刻意不再用「最大连续空洞」判级。** 侧脸检不出是常态，拿它判刑会把
    meld / mustard 这类反打镜头多的源大批误杀（实测误杀率 22% 与 52%）。
    空洞长度仍记进 stats 供人工审核参考，但不参与判级。
    """
    n = len(track)
    dets = [t for t in track if t is not None]
    det_rate = len(dets) / n if n else 0.0
    mean_sim = sum(t["sim"] for t in dets) / len(dets) if dets else 0.0
    heights = [t["bbox"][3] for t in dets]
    mean_h_ratio = (sum(heights) / len(heights) / frame_h) if heights and frame_h else 0.0
    gap_frames = max_gap(track)

    reasons = []
    if det_rate < MIN_DET_RATE:
        reasons.append(f"det_rate={det_rate:.2f}<{MIN_DET_RATE}")
    if mean_sim < MIN_MEAN_SIM:
        reasons.append(f"mean_sim={mean_sim:.3f}<{MIN_MEAN_SIM}")

    if reasons:
        status = "drop"
    elif det_rate < LOW_DET_RATE:
        status = "low_confidence"
        reasons = [f"det_rate={det_rate:.2f}<{LOW_DET_RATE}"]
    else:
        status = "ok"

    stats = {
        "detected": len(dets),
        "face_present_ratio": round(det_rate, 4),
        "max_gap_frames": gap_frames,
        "max_gap_seconds": round(gap_frames / fps, 3) if fps else 0.0,
        "det_rate": round(det_rate, 4),
        "mean_sim": round(mean_sim, 4),
        "mean_face_h_ratio": round(mean_h_ratio, 4),
    }
    return stats, status, reasons


def coverage(track, side, centers):
    """检出帧里，人脸**完整**落在裁剪框内的比例。

    收紧 margin 会让脸占满画面（标注者看得清表情），但收过头会在人脸
    移动或凑近时切掉一部分。这个比例就是定 margin 的依据——不靠拍脑袋。
    """
    dets = [(i, t) for i, t in enumerate(track) if t is not None]
    if not dets or side <= 0:
        return 0.0
    inside = 0
    half = side / 2
    for i, t in dets:
        cx, cy = centers[i]
        x, y, w, h = t["bbox"]
        if (x >= cx - half and y >= cy - half
                and x + w <= cx + half and y + h <= cy + half):
            inside += 1
    return inside / len(dets)


def build(frames_cands, fps, frame_w, frame_h, margin=CROP_MARGIN):
    """完整流水：认人 → 算稳定框 → 判级。

    返回 (crop, stats, status, reasons)。crop 为 None 表示一帧都没认出人脸。
    """
    track = link_track(frames_cands, frame_h)
    stats, status, reasons = evaluate(track, fps, frame_h)
    mode, side, centers = stable_box(track, frame_w, frame_h, fps, margin)
    if centers is None:
        return None, stats, status, reasons
    stats["face_inside_ratio"] = round(coverage(track, side, centers), 4)
    present = [1 if track[i] is not None else 0 for i in range(len(centers))]
    visible = smooth_presence(present, fps)
    crop = {
        "mode": mode,
        "side": round(side, 2),
        # bbox 是该帧**实际检到**的人脸框，只在 present 时有值。
        # face 用 cx/cy + side 那个稳定大框（要稳、不能抖）；
        # body 用这个逐帧真框（要准、不能糊到旁边人脸上）。两者刻意不共用。
        "frames": [
            {"i": i, "cx": round(c[0], 2), "cy": round(c[1], 2),
             "present": present[i], "visible": visible[i],
             "bbox": ([round(v, 1) for v in track[i]["bbox"]]
                      if track[i] is not None else None)}
            for i, c in enumerate(centers)
        ],
    }
    # 黑屏比例按 visible 算——那才是标注者真正看到的，也用它判级
    vr = sum(visible) / len(visible) if visible else 0.0
    stats["visible_ratio"] = round(vr, 4)
    stats["black_ratio"] = round(1 - vr, 4)
    stats["flicker_cuts"] = len(_runs(visible, 0))

    # evaluate() 里按原始检出率判的那条作废，改用迟滞后的可见率；
    # mean_sim 那条（跟错人）与可见性无关，原样保留
    reasons = [r for r in reasons if not r.startswith("det_rate")]
    if vr < MIN_DET_RATE:
        reasons.append(f"visible={vr:.2f}<{MIN_DET_RATE}")
    if reasons:
        status = "drop"
    elif vr < LOW_DET_RATE:
        status, reasons = "low_confidence", [f"visible={vr:.2f}<{LOW_DET_RATE}"]
    else:
        status, reasons = "ok", []
    return crop, stats, status, reasons
