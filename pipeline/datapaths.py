"""素材准备流水线的数据根目录。

代码在仓库里，**数据不在**——`out/`、`models/`、`data/` 加起来十几 GB，
留在 Roihu 的 scratch 上。这个模块是两者之间唯一的接缝：
所有脚本都从这里取数据路径，不再各写各的绝对路径。

换机器或换存储位置时只需设 `XMER_DATA_ROOT`，代码一行不用改。
"""

import os
from pathlib import Path

DATA_ROOT = Path(
    os.environ.get("XMER_DATA_ROOT", "/scratch/project_2017416/yyy2026/XMER")
)

# 各阶段的数据目录，目录名沿用当初的编号，便于对照历史记录
POOL_DATA = DATA_ROOT / "04-conflict-sampling" / "0-conflict_sample_selection" / "data"
FRAMES_DIR = DATA_ROOT / "06-speaker-frames"
ALIGN_DIR = DATA_ROOT / "07-text-alignment"
MEDIA_DIR = DATA_ROOT / "08-material-prep"

# 流水线自己的代码根目录（pipeline/），用于跨阶段导入
PIPELINE_ROOT = Path(__file__).resolve().parent
# 标注平台仓库根目录，`build_tasks.py` 要用里面的 server/app
REPO_ROOT = PIPELINE_ROOT.parent


def stage_path(stage: str) -> Path:
    """某个阶段的源码目录，供跨阶段 sys.path.insert 用。"""
    return PIPELINE_ROOT / stage / "src"
