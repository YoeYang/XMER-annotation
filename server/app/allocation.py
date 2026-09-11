"""样本分配计划。

分配以**样本**为单位（一个样本 = 四个单模态任务，同一人全标），
锚点单独按覆盖度重复发放，再散布插入队列内部。
"""

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class PlanRow:
    annotator_id: str
    order_index: int
    sample_id: str
    is_anchor: bool


def even_split(
    sample_ids: list[str], annotator_ids: list[str], seed: int
) -> dict[str, list[str]]:
    """打乱后轮转发牌，各人数量最多差一个。"""
    if not annotator_ids:
        raise ValueError("至少需要一位标注者")
    shuffled = list(sample_ids)
    random.Random(seed).shuffle(shuffled)
    buckets: dict[str, list[str]] = {a: [] for a in annotator_ids}
    for position, sample_id in enumerate(shuffled):
        buckets[annotator_ids[position % len(annotator_ids)]].append(sample_id)
    return buckets


def spread_anchors(
    anchor_ids: list[str], annotator_ids: list[str], coverage: int, seed: int
) -> dict[str, list[str]]:
    """每个锚点发给 coverage 位**不同**标注者，负载尽量均衡。

    coverage 决定一致性能算到什么程度：1 等于没有重叠，锚点白设。
    """
    if coverage < 1:
        raise ValueError("锚点覆盖度至少为 1")
    if coverage > len(annotator_ids):
        raise ValueError("锚点覆盖度不能超过标注者人数")
    rng = random.Random(seed)
    counts = {a: 0 for a in annotator_ids}
    buckets: dict[str, list[str]] = {a: [] for a in annotator_ids}
    for anchor in anchor_ids:
        # 先挑当前锚点最少的人，同分随机打破，避免固定偏向
        ranked = sorted(annotator_ids, key=lambda a: (counts[a], rng.random()))
        for annotator in ranked[:coverage]:
            buckets[annotator].append(anchor)
            counts[annotator] += 1
    return buckets


def interleave(base: list[str], anchors: list[str], seed: int) -> list[tuple[str, bool]]:
    """把锚点插进队列内部而非首尾，使其与普通样本处于同等疲劳水平。"""
    rng = random.Random(seed)
    queue: list[tuple[str, bool]] = [(sample_id, False) for sample_id in base]
    for anchor in anchors:
        position = rng.randrange(1, len(queue)) if len(queue) > 1 else len(queue)
        queue.insert(position, (anchor, True))
    return queue


def build_plan(
    pool_ids: list[str],
    anchor_ids: list[str],
    annotator_ids: list[str],
    coverage: int = 2,
    seed: int = 0,
) -> list[PlanRow]:
    """产出完整分配计划。锚点本就在池子里，先从均分的底池中剔除。"""
    anchors = set(anchor_ids)
    base = [sample_id for sample_id in pool_ids if sample_id not in anchors]
    split = even_split(base, annotator_ids, seed)
    spread = spread_anchors(anchor_ids, annotator_ids, coverage, seed)

    rows: list[PlanRow] = []
    for offset, annotator in enumerate(annotator_ids):
        queue = interleave(split[annotator], spread[annotator], seed + offset)
        rows.extend(
            PlanRow(annotator, order_index, sample_id, is_anchor)
            for order_index, (sample_id, is_anchor) in enumerate(queue)
        )
    return rows
