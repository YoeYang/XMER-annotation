#!/bin/bash
#SBATCH --job-name=xmer-rev2
#SBATCH --account=project_2005312
#SBATCH --partition=small
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --output=%x-%j.out
cd "$SLURM_SUBMIT_DIR"
export PYTHONUSERBASE=/projappl/project_2017416/python-package/conflict-sampling-x86
export OPENCV_LOG_LEVEL=ERROR
FF=/projappl/project_2017416/python-package/conflict-sampling-x86/lib/python3.9/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2
rm -rf out/review_body out/review_body_small
/usr/bin/python3 -u src/render.py --samples out/review_all.txt --out out/review_body --kind body 2>&1 | tail -3
mkdir -p out/review_body_small
for f in out/review_body/*.body.mp4; do
  b=$(basename "$f")
  # 审核用，缩到高 360 省体积；判「遮挡块盖没盖住五官」够用了
  "$FF" -hide_banner -loglevel error -y -i "$f" -vf "scale=-2:min(360\,ih)" \
     -c:v libx264 -preset veryfast -crf 26 -pix_fmt yuv420p "out/review_body_small/$b"
done
echo "body 原始 $(du -sh out/review_body|cut -f1)  缩放后 $(du -sh out/review_body_small|cut -f1)"
