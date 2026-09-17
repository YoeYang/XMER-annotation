#!/bin/bash
#SBATCH --job-name=xmer-build
#SBATCH --account=project_2005312
#SBATCH --partition=small
#SBATCH --cpus-per-task=16
#SBATCH --mem=24G
#SBATCH --time=00:20:00
#SBATCH --output=logs/build-%A_%a.out
#
# 构建 V3 五模态素材并对齐时长。x86 分区，纯 CPU。
# 全量：  sbatch --array=0-31 build_media.sbatch
# 试点：  sbatch --array=0-0 --partition=test build_media.sbatch --samples out/pilot50.txt
cd "$SLURM_SUBMIT_DIR"
export PYTHONUSERBASE=/projappl/project_2017416/python-package/conflict-sampling-x86
export OPENCV_LOG_LEVEL=ERROR
export OMP_NUM_THREADS=1
OF=${SLURM_ARRAY_TASK_COUNT:-1}
/usr/bin/python3 -u src/build_media.py --shard "${SLURM_ARRAY_TASK_ID:-0}" --of "$OF" \
    --workers "$SLURM_CPUS_PER_TASK" "$@"
