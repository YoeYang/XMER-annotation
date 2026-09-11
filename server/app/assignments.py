"""分配的落库逻辑。

CLI（`manage.py apply-plan`）与管理端 API 共用这里，避免两处各写一套
"样本展开成四个模态任务"而慢慢跑偏。
"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import Assignment, Task


def tasks_by_sample(session: Session) -> dict[str, list[str]]:
    """source_id → 该样本下全部任务，按 task_id 排序保证结果稳定。"""
    grouped: dict[str, list[str]] = {}
    for task_id, source_id in session.execute(select(Task.task_id, Task.source_id)):
        grouped.setdefault(source_id, []).append(task_id)
    for task_ids in grouped.values():
        task_ids.sort()
    return grouped


def replace_assignments(
    session: Session,
    annotator_id: str,
    phase: str,
    queue: list[tuple[str, bool]],
    grouped: dict[str, list[str]] | None = None,
) -> tuple[int, list[str]]:
    """用 `queue`（[(sample_id, is_anchor)]，顺序即队列顺序）整体替换某人某阶段的分配。

    返回 (写入的任务数, 没有对应任务的样本)。整体替换而非增量合并：
    分配是一份完整计划，半新半旧的队列比错误的队列更难排查。
    """
    grouped = tasks_by_sample(session) if grouped is None else grouped
    session.execute(
        delete(Assignment).where(
            Assignment.annotator_id == annotator_id, Assignment.phase == phase
        )
    )
    written, missing = 0, []
    for order_index, (sample_id, is_anchor) in enumerate(queue):
        task_ids = grouped.get(sample_id)
        if not task_ids:
            missing.append(sample_id)
            continue
        for task_id in task_ids:
            session.add(
                Assignment(
                    annotator_id=annotator_id,
                    task_id=task_id,
                    phase=phase,
                    order_index=order_index,
                    is_anchor=is_anchor,
                )
            )
            written += 1
    return written, missing
