#!/bin/bash
#SBATCH --job-name=xmer-rev3
#SBATCH --account=project_2005312
#SBATCH --partition=test
#SBATCH --cpus-per-task=8
#SBATCH --mem=12G
#SBATCH --time=00:14:00
#SBATCH --output=%x-%j.out
cd "$SLURM_SUBMIT_DIR"
FF=/projappl/project_2017416/python-package/conflict-sampling-x86/lib/python3.9/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2
rm -rf out/review_pair; mkdir -p out/review_pair
n=0
for f in out/review_vids/*.face.mp4; do
  sid=$(basename "$f" .face.mp4)
  b="out/review_body/${sid}.body.mp4"
  [ -f "$b" ] || continue
  # 左 face（320 见方）右 body（等高），一眼同时看两个模态
  "$FF" -hide_banner -loglevel error -y -i "$f" -i "$b" \
    -filter_complex "[1:v]scale=-2:320[bb];[0:v][bb]hstack=inputs=2[o]" \
    -map "[o]" -c:v libx264 -preset veryfast -crf 27 -pix_fmt yuv420p \
    "out/review_pair/${sid}.mp4" && n=$((n+1))
done
echo "合成 $n 个"
du -sb out/review_pair | awk '{printf "体积 %.1fMB\n", $1/1048576}'
