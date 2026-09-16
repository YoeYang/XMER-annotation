#!/bin/bash
#SBATCH --job-name=xmer-prep
#SBATCH --account=project_2017416
#SBATCH --partition=gpumedium
#SBATCH --array=0-7
#SBATCH --cpus-per-task=8
#SBATCH --mem=12G
#SBATCH --time=03:00:00
#SBATCH --output=logs/prep-%A_%a.out

module load python-data/3.12-20.04
module load ffmpeg/7.1
cd "$SLURM_SUBMIT_DIR"
python3 src/prepare.py --shard "$SLURM_ARRAY_TASK_ID" --of 8 --out out
