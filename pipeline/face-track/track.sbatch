#!/bin/bash
#SBATCH --job-name=xmer-track
#SBATCH --account=project_2005312
#SBATCH --partition=small
#SBATCH --cpus-per-task=16
#SBATCH --mem=24G
#SBATCH --time=01:00:00
#SBATCH --output=logs/track-%A_%a.out
#
# 逐帧人脸轨迹。x86 分区，纯 CPU（YuNet/SFace 都是 OpenCV 的 ONNX CPU 实现）。
# 全量：  sbatch --array=0-31 track.sbatch
# 试点：  sbatch --array=0-0 track.sbatch --samples out/pilot50.txt
cd "$SLURM_SUBMIT_DIR"
export PYTHONUSERBASE=/projappl/project_2017416/python-package/conflict-sampling-x86
export OPENCV_LOG_LEVEL=ERROR
export OMP_NUM_THREADS=1          # 进程级并行，别让 OpenCV 再开线程互相抢核
OF=${SLURM_ARRAY_TASK_COUNT:-1}
/usr/bin/python3 -u src/track.py --shard "${SLURM_ARRAY_TASK_ID:-0}" --of "$OF" \
    --workers "$SLURM_CPUS_PER_TASK" "$@"
