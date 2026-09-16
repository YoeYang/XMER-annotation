#!/bin/bash
#SBATCH --job-name=xmer-diag
#SBATCH --account=project_2005312
#SBATCH --partition=test
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
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
ids=[x.strip() for x in open("out/review_drop.txt").read().split()][:12]
for sid in ids:
    tmpl,err=T.template(sid)
    if tmpl is None: print(sid,'模板失败',err); continue
    frames,fps=T.read_video(MEDIA_DIR/'out'/'media'/sid/'visual.mp4')
    h,w=frames[0].shape[:2]
    per=[]   # 每帧：所有候选脸的 embedding 与对静帧的相似度
    for fr in frames:
        fs=T._faces(fr)
        row=[]
        for f in fs:
            e=T._embed(fr,f)
            row.append((f['bbox'],f['det'],float(np.dot(e,tmpl)),e))
        per.append(row)
    # 现有口径选出的轨迹
    cands=[[{'bbox':b,'det':d,'sim':s} for b,d,s,_ in row] for row in per]
    trk=tc.link_track(cands,h)
    acc=[i for i,t in enumerate(trk) if t is not None]
    # 用「片内已接受帧」的平均 embedding 当第二模板
    vecs=[]
    for i in acc:
        bb=trk[i]['bbox']
        for b,d,s,e in per[i]:
            if abs(b[0]-bb[0])<1 and abs(b[1]-bb[1])<1: vecs.append(e)
    if not vecs: print(sid,'无可用帧'); continue
    inv=np.mean(vecs,axis=0); inv/=np.linalg.norm(inv)
    s_old=[max([s for _,_,s,_ in row], default=0) for row in per]
    s_new=[max([max(s,float(np.dot(e,inv))) for _,_,s,e in row], default=0) for row in per]
    print(f"\n=== {sid}")
    print(f"  对静帧模板   : 中位={np.median([x for x in s_old if x>0]):.3f}  >=0.25 的帧 {sum(1 for x in s_old if x>=0.25)}/{len(per)}")
    print(f"  对片内模板   : 中位={np.median([x for x in s_new if x>0]):.3f}  >=0.25 的帧 {sum(1 for x in s_new if x>=0.25)}/{len(per)}")
    print(f"  有检出脸的帧 : {sum(1 for row in per if row)}/{len(per)}")
PY
