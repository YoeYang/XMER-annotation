"""锚点质量（2026-10-01 版）：拿标注者的曲线和 Yoe 的参考曲线比。

锚点的定义见 `app/anchors.py`。比对按 (子任务, 维度) 逐条做，两边都只取最新一版提交：

* 两条曲线按 `STEP` 秒重采样到同一时间轴，取「上一个有效采样」的值——标注者松手时
  线就停在那儿，保持比插值更贴近真实。
* **MAE**（平均绝对差，量程 -1…1）是主指标，平的曲线也能算。
* **r**（皮尔逊相关）看走势是否一致；任一边几乎不动（标准差 < `FLAT`）时不算，记 None。
"""

import math
import statistics
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .anchors import stage_queue, training_task_ids
from .completion import latest_submissions
from .config import DIMENSIONS, MODALITIES, is_reference
from .export import assemble_samples
from .models import Assignment, Task

STEP = 0.1
FLAT = 0.02
# 平均 MAE 超过全组中位数这么多倍、且比对条数够，就标出来
OUTLIER = 1.5
MIN_COMPARED = 5
CURVE_POINTS = 60


def resample(samples: list[dict], end: float) -> list[float]:
    points = sorted((s["media_time"], s["value"]) for s in samples if s.get("is_valid", True))
    if not points:
        return []
    grid, out, i, current = [], [], 0, points[0][1]
    steps = max(1, int(end / STEP) + 1)
    for k in range(steps):
        t = k * STEP
        while i < len(points) and points[i][0] <= t + 1e-9:
            current = points[i][1]
            i += 1
        out.append(current)
    return out


def compare(mine: list[float], ref: list[float]) -> dict:
    n = min(len(mine), len(ref))
    if n == 0:
        return {"mae": None, "r": None}
    a, b = mine[:n], ref[:n]
    mae = sum(abs(x - y) for x, y in zip(a, b)) / n
    r = None
    if n >= 3:
        sa, sb = statistics.pstdev(a), statistics.pstdev(b)
        if sa >= FLAT and sb >= FLAT:
            ma, mb = sum(a) / n, sum(b) / n
            r = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (n * sa * sb)
    return {"mae": round(mae, 3), "r": None if r is None else round(r, 2)}


def _downsample(values: list[float]) -> list[float]:
    if len(values) <= CURVE_POINTS:
        return [round(v, 3) for v in values]
    step = len(values) / CURVE_POINTS
    return [round(values[int(i * step)], 3) for i in range(CURVE_POINTS)]


def _mean(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 3) if values else None


def _median(values):
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 2) if values else None


def anchor_report(session: Session, stage: int, detail_for: str | None = None) -> dict:
    """全组汇总；`detail_for` 给出某位标注者时，附上他每条锚点的两条曲线。"""
    owners = stage_queue(session, stage)
    training = training_task_ids(session)
    latest = latest_submissions(session)
    ref: dict[tuple[str, str], str] = {}
    mine: dict[tuple[str, str, str], str] = {}
    for sub in latest:
        if sub.task_id not in owners or sub.task_id in training:
            continue
        if is_reference(sub.annotator_id):
            ref[sub.task_id, sub.dimension] = sub.attempt_id
        elif sub.annotator_id in owners[sub.task_id]:
            mine[sub.annotator_id, sub.task_id, sub.dimension] = sub.attempt_id

    tasks = {t.task_id: t for t in session.scalars(
        select(Task).where(Task.task_id.in_(sorted({t for t, _ in ref}))))} if ref else {}
    queued_for_ref = set(session.scalars(
        select(Assignment.task_id).where(Assignment.status == "active",
                                         Assignment.is_anchor.is_(True))))
    ref_done = {t for t, d in ref if all((t, dim) in ref for dim in DIMENSIONS)}

    curves: dict[str, list[float]] = {}

    def curve(attempt_id: str, end: float) -> list[float]:
        if attempt_id not in curves:
            curves[attempt_id] = resample(assemble_samples(session, attempt_id), end)
        return curves[attempt_id]

    people = sorted({a for names in owners.values() for a in names})
    rows, detail = [], []
    for aid in people:
        ready = [t for t in ref_done if aid in owners[t]]
        scores = defaultdict(list)
        compared = 0
        for task_id in sorted(ready, key=lambda t: (MODALITIES.index(tasks[t].modality), t)):
            task = tasks[task_id]
            item = {"task_id": task_id, "modality": task.modality}
            got_any = False
            for dim in DIMENSIONS:
                attempt = mine.get((aid, task_id, dim))
                if attempt is None:
                    continue
                got_any = True
                theirs, reference = curve(attempt, task.duration), curve(ref[task_id, dim], task.duration)
                score = compare(theirs, reference)
                scores[dim].append(score)
                if aid == detail_for:
                    item[dim] = {**score, "mine": _downsample(theirs), "ref": _downsample(reference)}
            if got_any:
                compared += 1
                if aid == detail_for:
                    detail.append(item)
        rows.append({
            "annotator_id": aid,
            "ready": len(ready),
            "compared": compared,
            **{f"mae_{dim}": _mean(s["mae"] for s in scores[dim]) for dim in DIMENSIONS},
            **{f"r_{dim}": _median(s["r"] for s in scores[dim]) for dim in DIMENSIONS},
        })

    overall = [statistics.mean([r[f"mae_{d}"] for d in DIMENSIONS if r[f"mae_{d}"] is not None])
               for r in rows if r["compared"] >= MIN_COMPARED
               and any(r[f"mae_{d}"] is not None for d in DIMENSIONS)]
    baseline = statistics.median(overall) if overall else None
    for r in rows:
        maes = [r[f"mae_{d}"] for d in DIMENSIONS if r[f"mae_{d}"] is not None]
        r["outlier"] = bool(baseline and r["compared"] >= MIN_COMPARED and maes
                            and statistics.mean(maes) > baseline * OUTLIER)

    reference_progress = {
        "queued": len(queued_for_ref & set(owners)),
        "done": len(ref_done),
        "done_from_queue": len(ref_done & queued_for_ref),
    }
    out = {
        "stage": stage,
        "reference": reference_progress,
        "baseline_mae": None if baseline is None else round(baseline, 3),
        "annotators": rows,
    }
    if detail_for is not None:
        out["detail"] = {"annotator_id": detail_for, "items": detail}
    return out
