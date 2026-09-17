#!/bin/bash
# 在登录节点直接建素材。作业本身只有几分钟的量，排 small 队列反而等更久。
# 登录节点是 ARM，必须用 python-data 自带的 ffmpeg（ARM 上唯一带 libx264 的）。
cd "$(dirname "$0")"
export PYTHONUSERBASE=/projappl/project_2017416/python-package/conflict-sampling
module load python-data/3.12-20.04 >/dev/null 2>&1
export XMER_FFMPEG=$(command -v ffmpeg)
export OPENCV_LOG_LEVEL=ERROR OMP_NUM_THREADS=1
exec python3 -u src/build_media.py --workers "${1:-24}"
