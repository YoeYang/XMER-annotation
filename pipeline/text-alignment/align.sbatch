#!/bin/bash
#SBATCH --job-name=xmer-align
#SBATCH --account=project_2017416
#SBATCH --partition=gpumedium
#SBATCH --array=0-3
#SBATCH --gres=gpu:gh200:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=24G
#SBATCH --time=02:00:00
#SBATCH --output=logs/align-%A_%a.out

module load python-pytorch/2.13
module load ffmpeg/7.1
export HF_HOME=$SLURM_SUBMIT_DIR/models
export TORCH_HOME=$SLURM_SUBMIT_DIR/models
export OMP_NUM_THREADS=8
cd "$SLURM_SUBMIT_DIR"
python3 -c "import torch; print('CUDA:', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
python3 src/run_all.py --shard "$SLURM_ARRAY_TASK_ID" --of 4
