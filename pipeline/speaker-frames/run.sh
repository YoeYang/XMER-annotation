#!/bin/bash
# 说话人静帧预处理。每步都可断点续跑，重跑自动跳过已完成的样本。
#
#   ./run.sh all        按顺序跑完整流程（下面 1-7 步）
#   ./run.sh scan       1. 全量本地人脸扫描与分桶（纯 CPU，约 45 分钟 / 22 核）
#   ./run.sh gallery    2. 用 meld/mustard 单人桶自动建角色人脸库
#   ./run.sh match      3. meld/mustard 全帧人脸库匹配（零 API 成本）
#   ./run.sh local      4. iemocap/mosi 本地选帧（画面单人，零 API 成本）
#   ./run.sh gemini     5. chsims 全量 asd 判别 + meld/mustard 兜底（需 GEMINI_API_KEY）
#   ./run.sh verify     6. Gemini 独立复核（meld/mustard 认角色 + chsims 验唇动）
#   ./run.sh merge      7. 把复核结论并回 manifest
#   ./run.sh lips       8. 给存疑的 chsims 条目生成唇动对照条
#   ./run.sh review     生成人工核对联系表
#   ./run.sh report     查看进度与分桶统计
set -euo pipefail
cd "$(dirname "$0")"

# module load 那行不能接管道——管道会开子 shell，PATH 改动会丢
module load ffmpeg/7.1
module load python-data/3.12-20.04
export OPENCV_LOG_LEVEL=ERROR
export PYTHONPATH="$PWD/src:${PYTHONPATH:-}"

WORKERS=${WORKERS:-22}
CONC=${CONC:-6}
RPM=${RPM:-120}

step_scan()    { python3 -u src/scan.py --workers "$WORKERS" "$@"; }
step_gallery() { python3 -u src/build_gallery.py --workers "$WORKERS" "$@"; }
step_match()   { python3 -u src/match_gallery.py --workers "$WORKERS" "$@"; }
step_local()   { for s in iemocap mosi; do python3 -u src/pick_local.py --source "$s" "$@"; done; }
step_gemini()  {
  : "${GEMINI_API_KEY:?请先 export GEMINI_API_KEY}"
  # chsims 无说话人元数据，全量走 asd（单人桶也要跑：反打镜头下说话人可能在画外）；
  # meld/mustard 只剩 match 交棒过来的 deferred 条目
  for s in meld mustard chsims; do
    echo "=== $s ==="
    python3 -u src/pick_gemini.py --source "$s" --bucket all \
        --concurrency "$CONC" --rpm "$RPM" "$@"
  done
}
step_verify()  {
  : "${GEMINI_API_KEY:?请先 export GEMINI_API_KEY}"
  # 两批的复核问法不同：meld/mustard 问「这张脸是不是角色 X」，
  # chsims 无角色名，改问「说这句台词的是不是这张图里的人」
  echo "=== meld/mustard 复核 ==="
  python3 -u src/verify_gemini.py --sources meld,mustard \
      --concurrency "$CONC" --rpm "$RPM" "$@"
  echo "=== chsims 复核 ==="
  python3 -u src/verify_gemini.py --sources chsims --mode asd \
      --concurrency 5 --rpm 90 "$@"
}

case "${1:-report}" in
  scan|gallery|match|local|gemini|verify) "step_${1}" "${@:2}" ;;
  merge)  python3 -u src/merge_verify.py "${@:2}" ;;
  lips)   python3 -u src/lipstrip.py "${@:2}" ;;
  review) python3 -u src/build_review.py "${@:2}" ;;
  report) python3 -u src/report.py "${@:2}" ;;
  all)
    step_scan; step_gallery; step_match; step_local; step_gemini; step_verify
    python3 -u src/merge_verify.py
    python3 -u src/lipstrip.py
    python3 -u src/build_review.py
    python3 -u src/report.py ;;
  *) echo "未知步骤：$1"; exit 1 ;;
esac
