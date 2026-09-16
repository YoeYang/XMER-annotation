#!/bin/bash
#SBATCH --job-name=xmer-rev
#SBATCH --account=project_2005312
#SBATCH --partition=small
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --output=%x-%j.out
cd "$SLURM_SUBMIT_DIR"
export PYTHONUSERBASE=/projappl/project_2017416/python-package/conflict-sampling-x86
export OPENCV_LOG_LEVEL=ERROR
rm -rf out/review_sheets out/review_vids
/usr/bin/python3 -u src/preview.py --samples out/review_all.txt --out out/review_sheets --n 999
echo "=== 视频（只给有裁剪框的）==="
/usr/bin/python3 -u src/render.py --samples out/review_all.txt --out out/review_vids --kind face 2>&1 | tail -5
