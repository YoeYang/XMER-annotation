"""分配的落库逻辑。

CLI（`manage.py apply-plan`）与管理端 API 共用这里，避免两处各写一套而慢慢跑偏。

V3 起分配以**子任务**（样本 × 模态）为单位。V2 时是一行一个样本、落库时展开成
该样本下的全部模态任务——那样同一样本的各模态必然归同一个人，正是硬隔离要禁止的。
"""

import random

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import Assignment, Task


def assign_display_ids(session: Session, seed: int) -> list[tuple[str, str]]:
    """给还没有编号的样本发放 display_id，返回 [(display_id, source_id)] 全量映射。

    编号顺序是**打乱**的：若按 source_id 字母序发号，S0001–S0917 就全是
    chsims、往后整段是 iemocap，标注者从编号区间就能猜出数据来源和样本聚集。
    已有编号的样本绝不改动——编号一旦发给标注者就不能变，否则先前提交的
    结果对不上样本；增量导入的新样本从当前最大号往后接。
    """
    existing: dict[str, str] = {}
    pending: set[str] = set()
    for source_id, display_id in session.execute(
        select(Task.source_id, Task.display_id).distinct()
    ):
        if display_id:
            existing[source_id] = display_id
        else:
            pending.add(source_id)
    pending -= existing.keys()

    next_number = 1 + max(
        (int(value[1:]) for value in existing.values() if value[1:].isdigit()),
        default=0,
    )
    fresh = sorted(pending)
    random.Random(seed).shuffle(fresh)
    for offset, source_id in enumerate(fresh):
        existing[source_id] = f"S{next_number + offset:04d}"

    for source_id in fresh:
        session.execute(
            Task.__table__.update()
            .where(Task.source_id == source_id)
            .values(display_id=existing[source_id])
        )
    return sorted((display_id, sid) for sid, display_id in existing.items())


def tasks_by_sample_modality(session: Session) -> dict[tuple[str, str], str]:
    """(source_id, modality) → task_id。

    V3 的分配以子任务为单位，要按「样本 + 模态」精确定位。
    **不要靠拼 `f"{sample}::{modality}"` 猜 task_id**——那是在假设 id 的格式，
    换个命名就悄悄全部对不上；从库里查才是唯一可靠的路。
    """
    return {
        (source_id, modality): task_id
        for task_id, source_id, modality in session.execute(
            select(Task.task_id, Task.source_id, Task.modality)
        )
    }


def replace_assignments(
    session: Session,
    annotator_id: str,
    phase: str,
    queue: list[tuple[str, str, bool]],
    index: dict[tuple[str, str], str] | None = None,
) -> tuple[int, list[str]]:
    """用 `queue`（[(sample_id, modality, is_anchor)]，顺序即队列顺序）整体替换分配。

    V3 起队列以**子任务**为单位：一行一个 (样本, 模态)，而不是一行一个样本、
    四个模态一起发。硬隔离要求同一样本的各模态分给不同的人，样本粒度表达不了。

    返回 (写入的任务数, 没有对应任务的子任务)。整体替换而非增量合并：
    分配是一份完整计划，半新半旧的队列比错误的队列更难排查。
    """
    index = tasks_by_sample_modality(session) if index is None else index
    session.execute(
        delete(Assignment).where(
            Assignment.annotator_id == annotator_id, Assignment.phase == phase
        )
    )
    written, missing = 0, []
    for order_index, (sample_id, modality, is_anchor) in enumerate(queue):
        task_id = index.get((sample_id, modality))
        if task_id is None:
            missing.append(f"{sample_id}::{modality}")
            continue
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


# 占位符而非人名，来自 mustard 等数据集的原始元数据。
# 展示这些对认人毫无帮助（"PERSON" 不能告诉标注者该看谁），当作无姓名处理。
_PLACEHOLDER_NAMES = {"person", "all", "moderator", "member-girl", "others", "unknown"}


def clean_speaker_name(raw: str | None) -> str | None:
    """清洗说话人姓名，供素材导入时调用。

    在**导入时**清洗而不是在前端过滤：脏值一旦进库，之后每个消费方
    （前端、导出、分析脚本）都得各自再过滤一遍。

    角色描述（Flight Attendant、Policeman 之类）予以保留——它们对认人有用，
    不是脏值；只剔除纯占位符。
    """
    if not raw:
        return None
    # Windows-1252 的弯撇号被当成 latin-1 读进来的残留，如 Richard\x92s Date
    name = raw.replace("\x92", "’").replace("\x93", '"').replace("\x94", '"')
    name = name.strip()
    if not name:
        return None
    stem = name.rstrip("0123456789").strip().lower()
    return None if stem in _PLACEHOLDER_NAMES else name
