"""阶段 2：多人桶的说话人判别（Gemini）。

两种模式：
  name 模式（meld / mustard）——说话人姓名已知，只需在编号框里认出这个角色，送一张标注图即可。
  asd  模式（chsims）——无元数据，必须判断「谁在说话」，送视频 + 标注参考帧，让它回答编号。

模型只做单选（回答框编号），不输出坐标，避免归一化 bbox 换算出错。
可断点续跑、失败单独归桶、限速与并发可配。
"""
import argparse, json, sys, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from annotate import annotate, rank_reference_frames, to_jpeg
from common import (FACESCAN, FRAMES, MANIFEST, JsonlWriter, crop_face, ensure_dirs,
                    faces_for_pick, load_done, main_faces)

MAX_REF_FRAMES = 3      # 换帧重问的上限；过肩镜头常需第二帧才能看到说话人

SCHEMA = {
    "type": "object",
    "properties": {
        "choice": {"type": "integer",
                   "description": "目标人物的框编号；无法确定或都不是时填 0"},
        "confidence": {"type": "number", "description": "0 到 1 的把握程度"},
        "reason": {"type": "string", "description": "一句话依据"},
    },
    "required": ["choice", "confidence", "reason"],
}

PROMPT_NAME = """这是电视剧《{show}》的一个画面，画面里的人脸已用彩色方框编号标出。

请指出哪一个编号框里的人是 **{name}**。

规则：
- 只回答编号，不要输出坐标。
- 如果画面里没有 {name}，或你无法确定，choice 填 0。
- confidence 反映你的把握：明确认出填 0.9 以上，靠推测填 0.5 以下。"""

PROMPT_ASD = """第一个输入是一段 {dur} 秒的中文影视片段，说的台词是：「{text}」
第二个输入是该片段第 {t} 秒的一帧，画面里所有人脸已用彩色方框编号标出。

请判断：**这段台词是由哪一个编号框里的人说出的？**

判断依据（按可靠性排序）：
1. 唇部运动与语音同步的人
2. 台词内容、语气与人物身份、表情的匹配
3. 镜头语言（说话者通常是画面焦点）

规则：
- 只回答编号，不要输出坐标。
- 说话人不在参考帧里（例如是画外音或已切走），choice 填 0。
- confidence 反映把握：看清唇动同步填 0.9 以上，靠推测填 0.5 以下。"""


def _read_frame(video_path, idx):
    import cv2
    cap = cv2.VideoCapture(str(video_path))
    frame = None
    for i in range(idx + 1):
        if i < idx:
            if not cap.grab():
                break
            continue
        ok, f = cap.read()
        if ok:
            frame = f
    cap.release()
    return frame


def _refine_crop_frame(rec, ref_fr, chosen):
    """在其他扫描帧里找同一个人（框中心相近）更清晰的一帧，提升辨识度。

    只接受中心位移小于半个框宽的匹配，镜头一动就放弃，避免换成别人。
    """
    bx, by, bw, bh = chosen["bbox"]
    cx, cy = bx + bw / 2, by + bh / 2
    best, best_q = (ref_fr, chosen), chosen["score"] * (0.7 + 0.3)
    for fr in rec["frames"]:
        if fr["idx"] == ref_fr["idx"]:
            continue
        for f in main_faces(fr["faces"], rec["h"]):
            x, y, w, h = f["bbox"]
            if abs(x + w / 2 - cx) > 0.5 * bw or abs(y + h / 2 - cy) > 0.5 * bh:
                continue
            if not (0.6 < (w * h) / (bw * bh) < 1.7):     # 尺寸突变多半不是同一个人
                continue
            smax = max(x["sharp"] for x in rec["frames"]) or 1.0
            q = f["score"] * (0.7 + 0.3 * min(1.0, fr["sharp"] / smax))
            if q > best_q:
                best, best_q = (fr, f), q
    return best


def build_request(rec, mode, ref):
    """返回 (parts, mapping, ref_frame_entry, ref_image_bgr)；无候选时返回 None。"""
    import cv2
    from google.genai import types

    frame = _read_frame(rec["video_path"], ref["idx"])
    if frame is None:
        return None
    cands = faces_for_pick(ref["faces"], rec["h"])[0]
    if not cands:
        return None
    marked, mapping = annotate(frame, cands)
    img_part = types.Part.from_bytes(data=to_jpeg(marked), mime_type="image/jpeg")

    if mode == "name":
        show = (rec.get("extra") or {}).get("show") or "Friends"
        prompt = PROMPT_NAME.format(show=show, name=rec.get("speaker_name") or "?")
        parts = [prompt, img_part]
    else:
        data = Path(rec["video_path"]).read_bytes()
        vid_part = types.Part(
            inline_data=types.Blob(data=data, mime_type="video/mp4"),
            video_metadata=types.VideoMetadata(fps=3.0),   # 降采样省 token，唇动仍可辨
        )
        prompt = PROMPT_ASD.format(
            dur=rec.get("duration") or "?", t=ref["t"],
            text=(rec.get("extra") or {}).get("text") or "")
        parts = [prompt, vid_part, img_part]
    return parts, mapping, ref, frame


def process(rec, gem, mode):
    import cv2
    sid = rec["sample_id"]
    out = {"sample_id": sid, "source": rec["source"],
           "speaker_name": rec.get("speaker_name"),
           "frame_path": None, "source_time": None, "bbox": None,
           "method": "gemini", "confidence": 0.0, "status": "failed", "note": ""}
    if rec.get("error"):
        out["note"] = rec["error"]
        return out
    try:
        refs = rank_reference_frames(rec, k=MAX_REF_FRAMES)
        if not refs:
            out["note"] = "no_candidate_face"
            return out

        attempts = []
        for ref_try in refs:
            built = build_request(rec, mode, ref_try)
            if built is None:
                continue
            parts, mapping, ref, frame = built
            text, _ = gem.generate(parts, schema=SCHEMA)
            ans = json.loads(text)
            choice = int(ans.get("choice", 0))
            conf = float(ans.get("confidence", 0.0))
            reason = str(ans.get("reason", ""))[:160]
            attempts.append((choice, conf, reason, mapping, ref, frame))
            if choice in mapping:
                break                      # 认出来了就不用再换帧
        if not attempts:
            out["note"] = "no_candidate_face"
            return out

        choice, conf, reason, mapping, ref, frame = attempts[-1]
        if choice not in mapping:
            # 所有参考帧都问不出来：退回本地最大脸，标出来让人必看
            face = max(mapping.values(), key=lambda f: f["score"])
            out.update(method="gemini-fallback", status="needs_review",
                       confidence=0.0,
                       note=f"tried {len(attempts)} frames, model_choice=0; {reason}")
            conf = 0.0
        else:
            face = mapping[choice]
            out.update(status="ok" if conf >= 0.6 else "needs_review",
                       note=reason if conf >= 0.6 else f"low_conf; {reason}")

        use_fr, use_face = _refine_crop_frame(rec, ref, face)
        if use_fr["idx"] != ref["idx"]:
            frame2 = _read_frame(rec["video_path"], use_fr["idx"])
            if frame2 is not None:
                frame, face = frame2, use_face
                ref = use_fr

        img = crop_face(frame, face["bbox"])
        cv2.imwrite(str(FRAMES / f"{sid}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        out.update(frame_path=f"frames/{sid}.jpg", source_time=ref["t"],
                   bbox=[round(v, 1) for v in face["bbox"]],
                   confidence=round(conf, 4))
    except Exception as exc:
        out["note"] = f"{type(exc).__name__}: {exc}"[:200]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="meld / mustard / chsims")
    ap.add_argument("--mode", default="", help="name / asd；默认按来源推断")
    ap.add_argument("--bucket", default="multi")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--rpm", type=int, default=60)
    ap.add_argument("--out", default=str(MANIFEST))
    ap.add_argument("--dry-run", action="store_true", help="只估算请求数与成本，不调 API")
    args = ap.parse_args()

    mode = args.mode or ("asd" if args.source == "chsims" else "name")
    ensure_dirs()
    # status=deferred 是上游（match_gallery）主动交棒的条目，要当成未完成来处理
    done = {sid for sid, r in load_done(args.out).items() if r.get("status") != "deferred"}
    scans = [r for r in load_done(FACESCAN).values()
             if r["source"] == args.source
             and (args.bucket == "all" or r.get("bucket") == args.bucket)
             and r["sample_id"] not in done]
    scans.sort(key=lambda r: r["sample_id"])
    if args.limit:
        scans = scans[:args.limit]
    print(f"{args.source} / {mode} 模式：待处理 {len(scans)} 条", flush=True)
    if args.dry_run or not scans:
        est_in = 1400 if mode == "name" else 3500      # 每条粗估输入 token
        from gemini_client import PRICE_IN, PRICE_OUT
        print(f"预计输入 {len(scans)*est_in/1e6:.3f}M tok，"
              f"约 ${len(scans)*est_in/1e6*PRICE_IN + len(scans)*60/1e6*PRICE_OUT:.3f}")
        return

    from gemini_client import Gemini
    gem = Gemini(rpm=args.rpm)
    lock = threading.Lock()
    tally = {"ok": 0, "needs_review": 0, "failed": 0, "n": 0}
    with JsonlWriter(args.out) as w:
        def run(rec):
            out = process(rec, gem, mode)
            with lock:
                w.write(out)
                tally[out["status"]] += 1
                tally["n"] += 1
                if tally["n"] % 25 == 0 or tally["n"] == len(scans):
                    print(f"  {tally['n']}/{len(scans)} ok={tally['ok']} "
                          f"needs_review={tally['needs_review']} failed={tally['failed']} "
                          f"| {gem.usage.summary()}", flush=True)
        with ThreadPoolExecutor(args.concurrency) as ex:
            list(ex.map(run, scans))
    print(f"完成：{tally} | {gem.usage.summary()}")


if __name__ == "__main__":
    main()
