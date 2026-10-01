"""隐藏锚点（2026-10-01 版）。

锚点 = Yoe 在参考账号（REF-xx）上标过的、本阶段正式队列里的子任务。标注者的队列
一条不加，也看不出哪条是锚点；后台拿分到同一子任务的标注者曲线与 Yoe 的参考比对，
作为个体质量指标。

训练子任务不算锚点：标注者在训练复盘里看过它们的参考曲线。
"""

import random
from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import MODALITIES, STAGE_ACCOUNT, is_reference
from .models import Assignment, Submission, Task


def training_task_ids(session: Session) -> set[str]:
    return set(session.scalars(
        select(Assignment.task_id).where(Assignment.phase == "training").distinct()))


def stage_queue(session: Session, stage: int) -> dict[str, list[str]]:
    """本阶段正式子任务 → 分到它的正式账号。"""
    owners: dict[str, list[str]] = defaultdict(list)
    for annotator_id, task_id in session.execute(
        select(Assignment.annotator_id, Assignment.task_id)
        .where(Assignment.phase == "main", Assignment.status == "active")
    ):
        m = STAGE_ACCOUNT.match(annotator_id)
        if m and int(m["stage"]) == stage:
            owners[task_id].append(annotator_id)
    return owners


def reference_task_ids(session: Session) -> set[str]:
    """参考账号交过的子任务（任一维度）。"""
    return {
        task_id for annotator_id, task_id in session.execute(
            select(Submission.annotator_id, Submission.task_id).distinct())
        if is_reference(annotator_id)
    }


def pick_anchor_queue(owners: dict[str, list[str]], modality_of: dict[str, str],
                      size: int, seed: int = 0) -> list[str]:
    """挑 `size` 条子任务，排成**任何前缀都均衡**的队列。

    五个模态轮流出；每一步在当前模态里挑「两位标注者已有锚点数之和最小」的子任务，
    同分随机。Yoe 标到哪儿停，10 个人分到的锚点数都差不多。
    """
    rng = random.Random(seed)
    pools: dict[str, list[str]] = defaultdict(list)
    for task_id in sorted(owners):
        pools[modality_of[task_id]].append(task_id)
    for pool in pools.values():
        rng.shuffle(pool)
    load: Counter[str] = Counter()
    queue: list[str] = []
    while len(queue) < size and any(pools.values()):
        for modality in MODALITIES:
            pool = pools.get(modality)
            if not pool or len(queue) >= size:
                continue
            best = min(range(len(pool)), key=lambda i: sum(load[a] for a in owners[pool[i]]))
            task_id = pool.pop(best)
            queue.append(task_id)
            load.update(owners[task_id])
    return queue


def anchor_candidates(session: Session, stage: int) -> tuple[dict[str, list[str]], dict[str, str]]:
    """可补标的锚点：本阶段正式子任务，去掉训练子任务和参考账号已经交过的。"""
    owners = stage_queue(session, stage)
    skip = training_task_ids(session) | reference_task_ids(session)
    owners = {t: a for t, a in owners.items() if t not in skip}
    modality_of = {t: m for t, m in session.execute(select(Task.task_id, Task.modality))
                   if t in owners}
    return owners, modality_of
