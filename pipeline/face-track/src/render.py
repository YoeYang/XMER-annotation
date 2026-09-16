"""按轨迹切出 face.mp4 与 body.mp4 —— 标注者真正会看到的东西。

**face**：裁说话人的脸，统一正方形边长。
  * 可见的帧 → 裁框内画面
  * **不可见的帧 → 纯黑**，绝不把镜头里的另一个人当说话人给标注者看
  * 「可见」用的是 `visible` 而不是 `present`：逐帧检出会一帧有一帧无，
    照搬就会「真实帧/黑屏」高频交替，看着像屏闪、眼睛很痛。
    `trackcore.smooth_presence()` 已做过迟滞，短暂丢失不切黑。

**body**：原画面尺寸不变，只把说话人的五官盖掉。
  * **不黑屏**，也**不用迟滞**。遮挡跟着每帧**实际检到的人脸框**走，
    认不出的帧就不遮——若沿用 face 那套「短暂丢失继续保持」，遮挡块会停在
    原处，镜头一切就盖到别人脸上去了
  * **只蒙说话人一个人**。画面里别人的脸不能蒙：那块黑色本身就是在
    指认「该看谁的身体」，全蒙了标注者就不知道该读谁了
  * 遮挡块只要盖住五官即可，**宁小勿大**——盖到脖子肩膀就把身体语言一起吃掉了，
    而头部动作本身也是动作，露一点头顶没关系

  * 帧率与帧数与源视频**逐帧对齐**

**时长必须与源一致。** 前端加载时核对媒体实际时长与任务清单，差超过 0.25 秒
就拒绝打开该任务；而且同一样本五个模态共用一条时间轴，长度不一致的话
曲线合并时对不齐。所以这里不重采样、不丢帧、不补帧——源有多少帧就写多少帧，
写完还要核对一遍。

x86 上没有能编码 H.264 的 ffmpeg 模块（spack 那个不带 libx264，
cv2 的 VideoWriter 只有 mp4v 能开），用的是装在 conflict-sampling-x86 里的
静态构建，见记忆 `xmer-roihu-env-slurm`。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from datapaths import MEDIA_DIR

TRACKS = Path(__file__).resolve().parents[1] / "out" / "tracks"
FFMPEG = Path(
    "/projappl/project_2017416/python-package/conflict-sampling-x86/lib/python3.9"
    "/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"
)
BODY_MASK_EXPAND = 0.10
"""body 遮挡块相对检测框的外扩比例。

YuNet 的框本来就贴着五官，稍微外扩一点盖住边缘即可。**刻意取得很小**：
遮挡块大了会连脖子肩膀一起吃掉，而那正是 body 子任务要给标注者看的东西。
判据是「看不见五官」，不是「看不见整个头」。
"""

MASK_COLOR = (0, 0, 0)
"""纯色块，不用高斯模糊——模糊仍然泄露表情强度。"""

OUT_SIZE = 320
"""输出边长。

素材原生裁剪框差异极大（chsims 中位 ~470、iemocap 只有 ~95），但标注界面的
显示尺寸是固定的——输出尺寸不统一，标注者看到的画面会忽大忽小。统一到 320：
iemocap 会被上采样（源就那么糊，改不了），chsims 略微下采样。
"""


def render(sample_id, out_path, size=OUT_SIZE, crf=20):
    import cv2
    import numpy as np

    rec = json.loads((TRACKS / f"{sample_id}.json").read_text(encoding="utf-8"))
    crop = rec.get("crop")
    if not crop:
        return None, "no_crop"

    src = MEDIA_DIR / "out" / "media" / sample_id / "visual.mp4"
    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or rec["fps"]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{size}x{size}", "-r", f"{fps}",
         "-i", "-", "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
         "-pix_fmt", "yuv420p", str(out_path)],
        stdin=subprocess.PIPE,
    )

    black = np.zeros((size, size, 3), dtype="uint8")
    side = crop["side"]
    n = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        c = crop["frames"][min(n, len(crop["frames"]) - 1)]
        if not c["visible"]:
            proc.stdin.write(black.tobytes())
        else:
            h, w = frame.shape[:2]
            x0, y0 = int(round(c["cx"] - side / 2)), int(round(c["cy"] - side / 2))
            x1, y1 = x0 + int(round(side)), y0 + int(round(side))
            # 框已在 trackcore 里钳进画面，这里再兜一次底，越界处补黑而不是报错
            pad_l, pad_t = max(0, -x0), max(0, -y0)
            pad_r, pad_b = max(0, x1 - w), max(0, y1 - h)
            patch = frame[max(0, y0):min(h, y1), max(0, x0):min(w, x1)]
            if pad_l or pad_t or pad_r or pad_b:
                patch = cv2.copyMakeBorder(patch, pad_t, pad_b, pad_l, pad_r,
                                           cv2.BORDER_CONSTANT, value=(0, 0, 0))
            if patch.size == 0:
                patch = black
            else:
                patch = cv2.resize(patch, (size, size), interpolation=cv2.INTER_AREA)
            proc.stdin.write(patch.tobytes())
        n += 1
    cap.release()
    proc.stdin.close()
    proc.wait()

    written = _frame_count(out_path)
    if written != n:
        return None, f"帧数不符 源={n} 出={written}"
    return {"frames": n, "fps": fps, "size": size}, None


def render_body(sample_id, out_path, crf=20):
    """原尺寸输出，只把说话人的脸盖掉。不缩放、不黑屏。"""
    import cv2

    rec = json.loads((TRACKS / f"{sample_id}.json").read_text(encoding="utf-8"))
    crop = rec.get("crop")
    if not crop:
        return None, "no_crop"

    src = MEDIA_DIR / "out" / "media" / sample_id / "visual.mp4"
    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or rec["fps"]
    w, h = rec["w"], rec["h"]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{w}x{h}", "-r", f"{fps}",
         "-i", "-", "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
         "-pix_fmt", "yuv420p", str(out_path)],
        stdin=subprocess.PIPE,
    )

    n = 0
    masked = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        c = crop["frames"][min(n, len(crop["frames"]) - 1)]
        box = c.get("bbox")
        if box:
            bx, by, bw, bh = box
            ex, ey = bw * BODY_MASK_EXPAND, bh * BODY_MASK_EXPAND
            x0, y0 = int(round(bx - ex)), int(round(by - ey))
            x1, y1 = int(round(bx + bw + ex)), int(round(by + bh + ey))
            cv2.rectangle(frame, (max(0, x0), max(0, y0)), (min(w, x1), min(h, y1)),
                          MASK_COLOR, thickness=-1)
            masked += 1
        proc.stdin.write(frame.tobytes())
        n += 1
    cap.release()
    proc.stdin.close()
    proc.wait()

    written = _frame_count(out_path)
    if written != n:
        return None, f"帧数不符 源={n} 出={written}"
    return {"frames": n, "fps": fps, "size": f"{w}x{h}",
            "masked": masked, "leak": n - masked}, None


def _frame_count(path):
    """数实际可解码帧数。

    **不要用 `ffmpeg -c copy -f null -` 去数** —— 流拷贝不解码，不打印 frame= 计数，
    拿到的永远是 -1（我第一版就栽在这）。容器元数据也会虚报
    （iemocap 声称 266 帧实际只有 52 帧可解码），所以老老实实解一遍。
    """
    import cv2
    cap = cv2.VideoCapture(str(path))
    n = 0
    while True:
        ok, _ = cap.read()
        if not ok:
            break
        n += 1
    cap.release()
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--samples", required=True, help="样本 id 文件，或逗号分隔的 id")
    ap.add_argument("--out", default="out/face_preview")
    ap.add_argument("--size", type=int, default=OUT_SIZE)
    ap.add_argument("--kind", choices=["face", "body", "both"], default="face")
    args = ap.parse_args()

    p = Path(args.samples)
    ids = ([s.strip() for s in p.read_text().split() if s.strip()] if p.exists()
           else [s.strip() for s in args.samples.split(",") if s.strip()])

    out_dir = Path(args.out)
    kinds = ["face", "body"] if args.kind == "both" else [args.kind]
    for sid in ids:
        for kind in kinds:
            if kind == "face":
                info, err = render(sid, out_dir / f"{sid}.face.mp4", args.size)
            else:
                info, err = render_body(sid, out_dir / f"{sid}.body.mp4")
            if err:
                print(f"失败 {sid} {kind}: {err}", flush=True)
            else:
                extra = (f" 遮{info['masked']}/未遮{info['leak']}"
                         if "masked" in info else "")
                print(f"OK   {sid:32s} {kind:4s} {info['frames']:4d} 帧 @ "
                      f"{info['fps']:.3f}fps = {info['frames'] / info['fps']:.3f}s "
                      f"[{info['size']}]{extra}", flush=True)


if __name__ == "__main__":
    main()
