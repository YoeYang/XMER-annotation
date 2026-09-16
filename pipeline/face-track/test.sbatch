#!/bin/bash
#SBATCH --job-name=xmer-ft-t
#SBATCH --account=project_2005312
#SBATCH --partition=test
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=00:08:00
#SBATCH --output=%x-%j.out
cd "$SLURM_SUBMIT_DIR"
export PYTHONUSERBASE=/projappl/project_2017416/python-package/conflict-sampling-x86
export OPENCV_LOG_LEVEL=ERROR
/usr/bin/python3 -m pytest tests -q 2>&1 | tail -25
