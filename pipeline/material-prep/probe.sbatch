#!/bin/bash
#SBATCH --job-name=xmer-probe
#SBATCH --account=project_2017416
#SBATCH --partition=test
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:05:00
#SBATCH --output=logs/probe-%j.out
echo "arch: $(uname -m)"
module load ffmpeg/7.1 2>&1 | head -2
which ffmpeg ffprobe
python3 -VV
cd "$SLURM_SUBMIT_DIR"
python3 src/prepare.py --limit 2 --shard 0 --of 1 --out /tmp/probe-out && echo PREP-OK
