"""每日抽查（2026-10-01 版）：某人某天完成的子任务里随机抽几条，带曲线、素材与自动提示。

「某天」按 `monitor.LOCAL_TZ`（芬兰时间）。完成 = 两维都交了，完成时刻取两维中较晚的首交。
训练与正式都抽，各条标明阶段；曲线取每维最新一版。只读，处置走 `/attempts/{id}/flags`。
"""

import random
import statistics
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .anchor_quality import FLAT, compare, resample
from .anchors import training_task_ids
from .completion import latest_submissions
from .export import assemble_samples
from .config import DIMENSIONS, is_reference
from .models import Assignment, AttemptFlag, Submission, Task
from .monitor import LOCAL_TZ, _completion_times, _pace

# 只用了这么窄一段量程（-1…1 共 2）就提示
NARROW = 0.2
# 同一维重标到第几版就提示
MANY_REDOS = 3


def _stats(curve: list[float]) -> dict:
    if not curve:
        return {"spread": None, "flat": None}
    spread = max(curve) - min(curve)
    return {"spread": round(spread, 3),
            "flat": len(curve) >= 3 and statistics.pstdev(curve) < FLAT}


def spot_check(session: Session, annotator_id: str, day: date, n: int = 10,
               seed: int = 0) -> dict:
    start = datetime(day.year, day.month, day.day, tzinfo=LOCAL_TZ)
    end = start + timedelta(days=1)
    finished = _completion_times(session, [annotator_id]).get(annotator_id, {})
    today = sorted(t for t, at in finished.items() if start <= at < end)
    times = [finished[t] for t in today]
    phase_of = dict(session.execute(
        select(Assignment.task_id, Assignment.phase)
        .where(Assignment.annotator_id == annotator_id, Assignment.status == "active")).all())
    picked = sorted(random.Random(seed).sample(today, min(n, len(today))),
                    key=lambda t: finished[t])

    latest, refs = {}, {}
    for s in latest_submissions(session):
        if s.annotator_id == annotator_id:
            latest[s.task_id, s.dimension] = s
        elif is_reference(s.annotator_id):
            refs[s.task_id, s.dimension] = s
    revisions = dict(((t, d), c) for t, d, c in session.execute(
        select(Submission.task_id, Submission.dimension, func.count())
        .where(Submission.annotator_id == annotator_id)
        .group_by(Submission.task_id, Submission.dimension)))
    training = training_task_ids(session)
    flags: dict[str, str] = {}
    for attempt_id, flag in session.execute(
        select(AttemptFlag.attempt_id, AttemptFlag.flag).order_by(AttemptFlag.flagged_at)):
        flags[attempt_id] = flag
    tasks = {t.task_id: t for t in session.scalars(
        select(Task).where(Task.task_id.in_(today)))} if today else {}

    def curve_of(attempt_id: str, duration: float) -> list[float]:
        return resample(assemble_samples(session, attempt_id), duration)

    # 当天概况：全部完成条目的直线占比与平均量程（不只抽到的那几条）
    flat = rated = 0
    spread_values = []
    for task_id in today:
        for dim in DIMENSIONS:
            sub = latest.get((task_id, dim))
            if sub is None:
                continue
            st = _stats(curve_of(sub.attempt_id, tasks[task_id].duration))
            rated += 1
            flat += bool(st["flat"])
            if st["spread"] is not None:
                spread_values.append(st["spread"])
    sec_per_task, active_hours = _pace(times)

    items = []
    for task_id in picked:
        task = tasks[task_id]
        item = {
            "task_id": task_id,
            "modality": task.modality,
            "phase": phase_of.get(task_id, "?"),
            "src": task.src,
            "duration": task.duration,
            "speaker_ref_src": task.speaker_ref_src,
            "completed_at": finished[task_id].isoformat(),
            "dims": {},
        }
        for dim in DIMENSIONS:
            sub = latest[task_id, dim]
            mine = curve_of(sub.attempt_id, task.duration)
            ref_sub = refs.get((task_id, dim))
            ref = (curve_of(ref_sub.attempt_id, task.duration)
                   if ref_sub and task_id not in training else None)
            notes = []
            st = _stats(mine)
            if st["flat"]:
                notes.append("几乎不动")
            elif st["spread"] is not None and st["spread"] < NARROW:
                notes.append("量程很窄")
            if revisions.get((task_id, dim), 0) >= MANY_REDOS:
                notes.append(f"重标 {revisions[task_id, dim]} 版")
            item["dims"][dim] = {
                "attempt_id": sub.attempt_id,
                "revisions": revisions.get((task_id, dim), 0),
                "curve": [round(v, 3) for v in mine],
                "ref": None if ref is None else [round(v, 3) for v in ref],
                "vs_ref": None if ref is None else compare(mine, ref),
                **st,
                "notes": notes,
                "flag": flags.get(sub.attempt_id),
            }
        items.append(item)

    return {
        "annotator_id": annotator_id,
        "date": day.isoformat(),
        "summary": {
            "completed": len(today),
            "sec_per_task": round(sec_per_task, 1) if sec_per_task else None,
            "active_hours": round(active_hours, 1),
            "flat_share": round(flat / rated, 2) if rated else None,
            "mean_spread": round(statistics.mean(spread_values), 2) if spread_values else None,
        },
        "items": items,
    }
