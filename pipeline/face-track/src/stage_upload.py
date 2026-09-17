"""把素材整理成**按编号命名**的目录树，供上传到线上。

Roihu 上的目录一律保持原始样本名（`meld_dia17_utt6/`）——排查时得认得出
哪个是哪个，换成 `S0123` 反而寸步难行。但线上那份必须只有编号：
`src` 会出现在浏览器地址栏、开发者工具和视频右键菜单里，
带上 `meld_` 前缀等于告诉标注者这是哪个数据集，`display_id` 就白发了。

产出 `out/upload/` 下的目录树，里面全是**硬链接**——同一份数据不占第二份
空间，而且改不到源文件（硬链接只是多一个名字，删掉这边不影响那边）。
跨文件系统时自动退回复制。

用法：

    python3 src/stage_upload.py            # 建目录树
    python3 src/stage_upload.py --check    # 只核对，不写

之后把 `out/upload/media` 与 `out/upload/transcripts` 同步到线上的
`/pool/v3/` 下（Caddy 路由见 README）。
"""
import argparse
import csv
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from datapaths import FRAMES_DIR, REPO_ROOT  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "out"
MEDIA_V3 = ROOT / "media_v3"
TRANSCRIPTS_V3 = ROOT / "transcripts_v3"
FRAMES = FRAMES_DIR / "out" / "frames"
UPLOAD = ROOT / "upload"
TASKS = ROOT / "tasks_import_v3.json"
DISPLAY_IDS = REPO_ROOT / "server" / "plans" / "display_ids.csv"

MEDIA_FILES = ("face.mp4", "body.mp4", "audio.m4a", "audiovisual.mp4")
"""要上传的媒体。

`visual.mp4` **不在其列**：V3 的五个模态里没有它，它只是构建 face/body 的
中间产物，传上去白占空间。

说话人静帧不在这里——它在 06 的产物目录，与 `build_tasks.py` 同一处来源，
见下面的 `FRAMES`。
"""


def link(src: Path, dst: Path) -> str:
    """硬链接优先，跨文件系统退回复制。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
        return "link"
    except OSError:
        shutil.copy2(src, dst)
        return "copy"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="只核对，不写文件")
    args = ap.parse_args()

    with DISPLAY_IDS.open(encoding="utf-8") as f:
        numbers = {row["source_id"]: row["display_id"] for row in csv.DictReader(f)}

    # 以清单为准，而不是扫目录：清单已经剔除过判死的样本，
    # 扫目录会把它们一并传上去
    tasks = json.loads(TASKS.read_text(encoding="utf-8"))
    samples = sorted({t["source_id"] for t in tasks})

    missing, modes = [], {"link": 0, "copy": 0}
    for sid in samples:
        code = numbers[sid]
        for name in MEDIA_FILES:
            src = MEDIA_V3 / sid / name
            if not src.exists():
                missing.append(f"{sid}/{name}")
                continue
            if not args.check:
                modes[link(src, UPLOAD / "media" / code / name)] += 1
        # 静帧读 06 的产物，与 build_tasks.py 同一来源。缺了要报——
        # 清单里的 speaker_ref_src 会指向它，少一个就是标注页上一个 404，
        # 而多人场景里那张图是判断「该看谁」的唯一依据。
        frame = FRAMES / f"{sid}.jpg"
        if not frame.exists():
            missing.append(f"frames/{sid}.jpg")
        elif not args.check:
            modes[link(frame, UPLOAD / "media" / code / "speaker.jpg")] += 1
        src = TRANSCRIPTS_V3 / f"{sid}.json"
        if not src.exists():
            missing.append(f"transcripts/{sid}.json")
        elif not args.check:
            modes[link(src, UPLOAD / "transcripts" / f"{code}.json")] += 1

    print(f"样本 {len(samples)} 条")
    if not args.check:
        print(f"  硬链接 {modes['link']} 个，复制 {modes['copy']} 个 → {UPLOAD}")
    if missing:
        raise SystemExit(
            f"缺 {len(missing)} 个文件，先补齐再上传：{missing[:5]}"
        )
    print("文件齐全。")


if __name__ == "__main__":
    main()
