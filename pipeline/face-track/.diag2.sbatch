#!/bin/bash
#SBATCH --job-name=xmer-diag2
#SBATCH --account=project_2005312
#SBATCH --partition=test
#SBATCH --cpus-per-task=8
#SBATCH --mem=12G
#SBATCH --time=00:14:00
#SBATCH --output=%x-%j.out
cd "$SLURM_SUBMIT_DIR"
export PYTHONUSERBASE=/projappl/project_2017416/python-package/conflict-sampling-x86
export OPENCV_LOG_LEVEL=ERROR
/usr/bin/python3 - <<'PY'
import sys, json, numpy as np
sys.path.insert(0,'src'); sys.path.insert(0,'..')
import track as T, trackcore as tc
from datapaths import MEDIA_DIR
# 20 条「跟错人」判死的，逐条看锚点够不够
ids=[]
import glob
for p in sorted(glob.glob('out/tracks/*.json')):
    r=json.loads(open(p,encoding='utf-8').read())
    if r['status']=='drop' and any(x.startswith('mean_sim') for x in r['reasons']):
        ids.append(r['sample_id'])
print(f'「跟错人」判死共 {len(ids)} 条\n')
print(f"{'样本':32s} {'p90':>6s} {'max':>6s} {'>=.363':>7s} {'结论'}")
ok=0
for sid in ids:
    tmpl,err=T.template(sid)
    if tmpl is None: print(f'{sid:32s} 模板失败 {err}'); continue
    frames,fps=T.read_video(MEDIA_DIR/'out'/'media'/sid/'visual.mp4')
    if not frames: continue
    h=frames[0].shape[0]
    sims=[]
    for fr in frames:
        for f in T._faces(fr):
            if f['det']>=tc.MIN_DET and f['bbox'][3]>=tc.MIN_FACE_H_RATIO*h:
                sims.append(float(np.dot(T._embed(fr,f),tmpl)))
    if not sims: print(f'{sid:32s} 无候选脸'); continue
    a=np.array(sims); n=int((a>=0.363).sum())
    verdict='锚点充足' if n>=5 else ('锚点不足' if n>0 else '确实没认出过')
    if n>=5: ok+=1
    print(f'{sid:32s} {np.percentile(a,90):6.3f} {a.max():6.3f} {n:7d} {verdict}')
print(f'\n有 >=5 个确认锚点的: {ok}/{len(ids)} —— 这些能靠片内模板救回来')
PY
