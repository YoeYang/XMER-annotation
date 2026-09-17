"""分配的落库逻辑。

CLI（`manage.py apply-plan`）与管理端 API 共用这里，避免两处各写一套而慢慢跑偏。

V3 起分配以**子任务**（样本 × 模态）为单位。V2 时是一行一个样本、落库时展开成
该样本下的全部模态任务——那样同一样本的各模态必然归同一个人，正是硬隔离要禁止的。
"""

import random

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import (
    Annotator,
    Assignment,
    Attempt,
    AttemptFlag,
    SampleChunk,
    SampleNumber,
    Submission,
    Task,
)


def _next_number(session: Session, start: int) -> int:
    """下一个可用的号。已发出的号一律绕开，包括退役的。"""
    used = [
        int(value[1:])
        for (value,) in session.execute(select(SampleNumber.display_id))
        if value[1:].isdigit()
    ]
    highest = max(used, default=0)
    if start and start <= highest:
        raise ValueError(
            f"起始号 S{start:04d} 落在已发出的号段内（最大已发 S{highest:04d}）。"
            "编号只发不收，从更大的号起发，或不指定起始号自动接续。"
        )
    return start if start else highest + 1


def issue_numbers(
    session: Session, source_ids: list[str], start: int = 0, seed: int = 0
) -> list[tuple[str, str]]:
    """给还没有号的样本发号，返回本次新发的 [(display_id, source_id)]。

    发号顺序是**打乱**的：按 source_id 字母序发号的话，S0001–S0917 就全是
    chsims、往后整段是 iemocap，标注者从编号区间就能猜出数据来源和样本聚集。

    `start` 用来给一批样本另起号段（备份池从 S3500 起发，与主池的
    S0001–S3441 隔开一眼能分辨）。已经有号的样本原样不动。
    """
    taken = set(session.scalars(select(SampleNumber.source_id)))
    fresh = sorted(set(source_ids) - taken)
    if not fresh:
        return []

    number = _next_number(session, start)
    random.Random(seed).shuffle(fresh)
    issued = []
    for offset, source_id in enumerate(fresh):
        display_id = f"S{number + offset:04d}"
        session.add(SampleNumber(display_id=display_id, source_id=source_id))
        issued.append((display_id, source_id))
    return issued


def assign_display_ids(session: Session, seed: int) -> list[tuple[str, str]]:
    """给库里所有还没编号的样本发号，返回 [(display_id, source_id)] 全量映射。

    已有编号的样本绝不改动——编号一旦发给标注者就不能变，否则先前提交的
    结果对不上样本；增量导入的新样本从当前最大号往后接。
    """
    source_ids = list(session.scalars(select(Task.source_id).distinct()))
    issue_numbers(session, source_ids, seed=seed)
    session.flush()
    return sorted(
        (display_id, source_id)
        for display_id, source_id in session.execute(
            select(SampleNumber.display_id, SampleNumber.source_id)
        )
    )


def numbers_by_sample(session: Session) -> dict[str, str]:
    """source_id → display_id。下发任务时用它补上编号。"""
    return {
        source_id: display_id
        for display_id, source_id in session.execute(
            select(SampleNumber.display_id, SampleNumber.source_id)
        )
    }


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


def purge_annotator(session: Session, annotator_id: str) -> dict[str, int]:
    """删掉一个账号及其产出的一切，返回各表删了多少行。

    **不可恢复**：轮次、采样、提交、处置标记、分配、账号本身，全部清掉。
    删除顺序从叶到根，外键才不会挡路。

    管理端与 `manage.py drop-annotator` 共用这一份——两处各写一套的话，
    迟早有一处漏删某张表，留下指向已删账号的孤儿行。
    """
    attempt_ids = list(
        session.scalars(
            select(Attempt.attempt_id).where(Attempt.annotator_id == annotator_id)
        )
    )
    removed = {
        "attempt_flags": 0,
        "sample_chunks": 0,
        "submissions": 0,
        "attempts": 0,
        "assignments": 0,
    }
    if attempt_ids:
        removed["attempt_flags"] = session.execute(
            delete(AttemptFlag).where(AttemptFlag.attempt_id.in_(attempt_ids))
        ).rowcount
        removed["sample_chunks"] = session.execute(
            delete(SampleChunk).where(SampleChunk.attempt_id.in_(attempt_ids))
        ).rowcount
    removed["submissions"] = session.execute(
        delete(Submission).where(Submission.annotator_id == annotator_id)
    ).rowcount
    removed["attempts"] = session.execute(
        delete(Attempt).where(Attempt.annotator_id == annotator_id)
    ).rowcount
    removed["assignments"] = session.execute(
        delete(Assignment).where(Assignment.annotator_id == annotator_id)
    ).rowcount
    session.execute(delete(Annotator).where(Annotator.annotator_id == annotator_id))
    return removed
