"""阶段进度监控（2026-10-01 版）：管理页的监控面板与会话推送共用这一份数字。

只看某一阶段的正式账号（`P1-ZH-*` / `P1-EN-*`），镜像号、参考号、预览号不进来——
它们的数据不是研究数据，混进来进度会虚高。

**完成 = 两个维度都交了**，完成时刻取两维中较晚的首交时间（重标不改完成时刻）。
速度只用正式任务算：相邻两次完成间隔不超过 `ACTIVE_GAP` 的才计入有效标注时长，
中间去吃饭、睡觉的空档不算。
"""

import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import DIMENSIONS, STAGE_ACCOUNT
from .models import Annotator, Assignment, Attempt, Submission
from .timeutils import to_utc_iso

# 阶段一截止 10.7 当天结束。按芬兰时间：10.25 之前是夏令时 UTC+3，整个阶段一都在这之前
LOCAL_TZ = timezone(timedelta(hours=3))
DEADLINES = {1: datetime(2026, 10, 7, 23, 59, 59, tzinfo=LOCAL_TZ)}

ACTIVE_GAP = timedelta(minutes=10)
IDLE_AFTER = timedelta(hours=24)
# 有效间隔太少时，每条用时和预测都不可信，宁可显示「数据不足」
MIN_GAPS = 20
MIN_SPAN = timedelta(hours=6)


def _utc(value: datetime) -> datetime:
    # SQLite 读回会丢时区；库里存的本就是 UTC
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _iso(value: datetime | None) -> str | None:
    return to_utc_iso(value) if value else None


def _completion_times(session: Session, ids: list[str]) -> dict[str, dict[str, datetime]]:
    """标注者 → {子任务 → 完成时刻}。只有两维都交了的子任务才出现。"""
    first: dict[tuple[str, str], dict[str, datetime]] = defaultdict(dict)
    for annotator_id, task_id, dimension, submitted_at in session.execute(
        select(Submission.annotator_id, Submission.task_id, Submission.dimension,
               func.min(Submission.submitted_at))
        .where(Submission.annotator_id.in_(ids))
        .group_by(Submission.annotator_id, Submission.task_id, Submission.dimension)
    ):
        first[(annotator_id, task_id)][dimension] = _utc(submitted_at)
    done: dict[str, dict[str, datetime]] = defaultdict(dict)
    for (annotator_id, task_id), dims in first.items():
        if set(dims) >= set(DIMENSIONS):
            done[annotator_id][task_id] = max(dims.values())
    return done


def _pace(times: list[datetime]) -> tuple[float | None, float]:
    """(每条平均秒数, 有效标注小时)。间隔太少返回 None。"""
    times = sorted(times)
    gaps = [b - a for a, b in zip(times, times[1:]) if b - a <= ACTIVE_GAP]
    active = sum(gaps, timedelta()).total_seconds()
    if len(gaps) < MIN_GAPS:
        return None, active / 3600
    return active / len(gaps), active / 3600


def _task_seconds(times: list[datetime]) -> dict:
    """单条用时的分布：上一条提交 → 这一条提交，含熟悉、读说明与两维标注。

    间隔超过 `ACTIVE_GAP` 视为中途休息，那一条不计——否则最长会被吃饭睡觉拉到几小时。
    有效间隔不足 `MIN_GAPS` 时全部为 None。
    """
    times = sorted(times)
    gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:]) if b - a <= ACTIVE_GAP]
    if len(gaps) < MIN_GAPS:
        return {"sec_median": None, "sec_min": None, "sec_max": None}
    return {"sec_median": round(statistics.median(gaps), 1),
            "sec_min": round(min(gaps), 1), "sec_max": round(max(gaps), 1)}


def build_monitor(session: Session, stage: int, now: datetime) -> dict:
    now = _utc(now)
    deadline = DEADLINES.get(stage)
    accounts = [
        row for row in session.scalars(select(Annotator).order_by(Annotator.annotator_id))
        if (m := STAGE_ACCOUNT.match(row.annotator_id)) and int(m["stage"]) == stage
    ]
    ids = [row.annotator_id for row in accounts]

    queues: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for annotator_id, phase, task_id in session.execute(
        select(Assignment.annotator_id, Assignment.phase, Assignment.task_id)
        .where(Assignment.annotator_id.in_(ids), Assignment.status == "active")
    ):
        queues[annotator_id][phase].add(task_id)

    first_seen = dict(session.execute(
        select(Attempt.annotator_id, func.min(Attempt.started_at))
        .where(Attempt.annotator_id.in_(ids)).group_by(Attempt.annotator_id)
    ).all())
    last_attempt = dict(session.execute(
        select(Attempt.annotator_id, func.max(Attempt.server_received_at))
        .where(Attempt.annotator_id.in_(ids)).group_by(Attempt.annotator_id)
    ).all())
    touched: dict[str, set[str]] = defaultdict(set)
    for annotator_id, task_id in session.execute(
        select(Attempt.annotator_id, Attempt.task_id).distinct()
        .where(Attempt.annotator_id.in_(ids))
    ):
        touched[annotator_id].add(task_id)
    done = _completion_times(session, ids)

    local_midnight = now.astimezone(LOCAL_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    days_left = (deadline - now).total_seconds() / 86400 if deadline else None

    rows = []
    for annotator in accounts:
        aid = annotator.annotator_id
        training, main = queues[aid]["training"], queues[aid]["main"]
        finished = done.get(aid, {})
        main_times = sorted(t for task, t in finished.items() if task in main)
        main_done = len(main_times)
        remaining = len(main) - main_done
        last = max(
            [_utc(t) for t in (last_attempt.get(aid),) if t] + main_times
            + [t for task, t in finished.items() if task in training],
            default=None,
        )
        sec_per_task, active_hours = _pace(main_times)

        if main and remaining == 0:
            state = "done"
        elif main_done or touched[aid] & main:
            state = "annotating"
        elif annotator.trained_at:
            state = "trained"
        elif aid in first_seen:
            state = "training"
        else:
            state = "not_started"

        # 速度：最近 24 小时的完成数；开标不足 MIN_SPAN 时不预测
        recent = sum(1 for t in main_times if t > now - timedelta(hours=24))
        forecast = None
        if deadline and remaining and main_times and now - main_times[0] >= MIN_SPAN:
            window = min(timedelta(hours=24), now - main_times[0])
            per_day = sum(1 for t in main_times if t >= now - window) / (window / timedelta(days=1))
            forecast = {
                "per_day": round(per_day),
                "on_track": per_day * max(days_left, 0) >= remaining,
            }

        rows.append({
            "annotator_id": aid,
            "language": annotator.language,
            "state": state,
            "first_activity": _iso(_utc(first_seen[aid]) if aid in first_seen else None),
            "last_activity": _iso(last),
            "idle": bool(last and state not in ("done", "not_started") and now - last > IDLE_AFTER),
            "training": {
                "done": sum(1 for task in finished if task in training),
                "total": len(training),
                "trained_at": _iso(_utc(annotator.trained_at) if annotator.trained_at else None),
            },
            "main": {
                "done": main_done,
                "total": len(main),
                "percent": math.floor(main_done * 100 / len(main)) if main else 0,
                "today": sum(1 for t in main_times if t >= local_midnight),
                "last_24h": recent,
            },
            "pace": {
                "sec_per_task": round(sec_per_task, 1) if sec_per_task else None,
                **_task_seconds(main_times),
                "active_hours": round(active_hours, 1),
                "hours_left": round(remaining * sec_per_task / 3600, 1) if sec_per_task else None,
                "needed_per_day": math.ceil(remaining / days_left) if days_left and days_left > 0 and remaining else None,
                "forecast": forecast,
            },
        })

    return {
        "generated_at": to_utc_iso(now),
        "stage": stage,
        "deadline": _iso(deadline),
        "days_left": round(days_left, 1) if days_left is not None else None,
        "annotators": rows,
        "totals": {
            "annotators": len(rows),
            "started": sum(1 for r in rows if r["state"] != "not_started"),
            "trained": sum(1 for r in rows if r["training"]["trained_at"]),
            "main_done": sum(r["main"]["done"] for r in rows),
            "main_total": sum(r["main"]["total"] for r in rows),
            "today": sum(r["main"]["today"] for r in rows),
        },
    }
