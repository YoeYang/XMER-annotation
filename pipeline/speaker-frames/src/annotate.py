"""把候选人脸画成编号框，供 Gemini 做「选第几号」而非直接输出坐标。

这样绕开了归一化 0-1000 bbox 的换算与坐标顺序问题，
判别任务也从「定位」降级为「单选」，准确率与可校验性都更好。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import faces_for_pick, main_faces

COLORS = [(64, 200, 255), (80, 255, 120), (255, 140, 80), (200, 120, 255),
          (120, 220, 255), (255, 220, 90), (150, 255, 200), (255, 160, 200)]


def rank_reference_frames(rec, k=3):
    """挑最多 k 帧做参考图，候选人脸最多优先、其次最锐利。

    取多帧是因为过肩/反打镜头下说话人可能不在某一帧里——
    第一帧问不出结果时换一帧再问，比直接放弃划算得多。
    """
    scored = []
    for fr in rec["frames"]:
        n = len(faces_for_pick(fr["faces"], rec["h"])[0])
        if n:
            scored.append(((n, fr["sharp"]), fr))
    scored.sort(key=lambda x: x[0], reverse=True)
    picked = []
    for _, fr in scored:
        # 帧之间尽量拉开时间，避免连着的几帧是同一个镜头同一批人
        if all(abs(fr["idx"] - p["idx"]) >= 2 for p in picked):
            picked.append(fr)
        if len(picked) >= k:
            break
    return picked


def choose_reference_frame(rec):
    frames = rank_reference_frames(rec, k=1)
    return frames[0] if frames else None


def annotate(frame, faces):
    """在帧上画编号框；返回 (标注后的图, 编号->face 映射)。"""
    import cv2
    img = frame.copy()
    H, W = img.shape[:2]
    thick = max(2, round(min(H, W) / 300))
    scale = max(0.7, min(H, W) / 600)
    mapping = {}
    # 按 x 排序编号，人眼与模型都更容易对上「左起第几个」
    for i, f in enumerate(sorted(faces, key=lambda f: f["bbox"][0]), 1):
        x, y, w, h = (int(round(v)) for v in f["bbox"])
        c = COLORS[(i - 1) % len(COLORS)]
        cv2.rectangle(img, (x, y), (x + w, y + h), c, thick)
        label = str(i)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
        ly = max(th + 6, y - 4)
        cv2.rectangle(img, (x, ly - th - 6), (x + tw + 10, ly + 4), c, -1)
        cv2.putText(img, label, (x + 5, ly), cv2.FONT_HERSHEY_SIMPLEX, scale,
                    (20, 20, 20), thick, cv2.LINE_AA)
        mapping[i] = f
    return img, mapping


def to_jpeg(img, max_side=1024, quality=88):
    """缩到长边 max_side 再编码——识别身份用不上原生 1080p，省 token。"""
    import cv2
    H, W = img.shape[:2]
    if max(H, W) > max_side:
        s = max_side / max(H, W)
        img = cv2.resize(img, (int(W * s), int(H * s)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("jpeg encode failed")
    return buf.tobytes()
