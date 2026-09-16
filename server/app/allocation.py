"""子任务分配计划。

V3 起分配以**子任务**为单位（样本 × 模态），不再以样本为单位。

## 为什么改粒度

V2 时一行一个样本，**一个样本的所有模态全归同一个标注者**。到了 V3 这是最弱的
隔离——同一个人先看脸、再看身体、再听音频、再读文本，同一段素材看四五遍，
记忆污染拉满。Yoe 定的口径是**硬隔离**：一个标注者拿到的子任务，样本互不重复。

## 四条约束同时满足

* **隔离**：一个样本的 N 个模态发给 N 位**不同**的标注者（`isolation="strict"`）
* **锚点**：锚点样本要 `模态数 × coverage` 位不同的人，一致性才算得出来
* **负载**：每次从合格者里挑当前最闲的
* **模态均衡**：同分时看这个人该模态已有多少，避免有人专做 face、有人专做 text

## 冗余口径（容易记错）

**不是每条都标多遍**：普通样本覆盖度 1，只有锚点是 `coverage`。这一点沿用 V2，
没有改动——锚点是用来算标注者间一致性的，普通样本靠量取胜。
"""

import random
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class PlanRow:
    annotator_id: str
    order_index: int
    sample_id: str
    modality: str
    is_anchor: bool


class AllocationShortfall(RuntimeError):
    """人手不够，排不出满足约束的计划。

    与其偷偷少发几条（分析时才发现某些样本只有两个模态），不如当场报错，
    并把缺口说清楚：要么加人，要么降 coverage，要么关掉隔离。
    """


def _eligible(annotators, used, load, per_annotator):
    out = []
    for a in annotators:
        if a in used:
            continue
        if per_annotator and load[a] >= per_annotator:
            continue
        out.append(a)
    return out


def assign_subtasks(
    pool_ids,
    anchor_ids,
    annotator_ids,
    modalities,
    coverage=2,
    seed=0,
    per_annotator=0,
    isolation="strict",
):
    """把每个样本的各模态发给不同的标注者。

    返回 {annotator_id: [(sample_id, modality, is_anchor), ...]}，顺序未定，
    队列顺序由 `order_queue()` 另行安排。
    """
    if not annotator_ids:
        raise ValueError("至少需要一位标注者")
    if not modalities:
        raise ValueError("至少需要一个模态")
    if coverage < 1:
        raise ValueError("锚点覆盖度至少为 1")
    if isolation not in ("strict", "off"):
        raise ValueError("isolation 只能是 strict 或 off")

    anchors = set(anchor_ids)
    if isolation == "strict":
        need = len(modalities) * coverage
        if need > len(annotator_ids):
            raise AllocationShortfall(
                f"硬隔离下一个锚点样本需要 {need} 位不同的标注者"
                f"（{len(modalities)} 模态 × 覆盖度 {coverage}），"
                f"但只有 {len(annotator_ids)} 位。加人、降 coverage，或关掉隔离。"
            )

    rng = random.Random(seed)
    order = list(pool_ids)
    rng.shuffle(order)

    buckets = defaultdict(list)
    load = {a: 0 for a in annotator_ids}
    per_mod = {a: defaultdict(int) for a in annotator_ids}

    for sample_id in order:
        is_anchor = sample_id in anchors
        wanted = [m for m in modalities for _ in range(coverage if is_anchor else 1)]
        # 同一样本内已经用掉的人。isolation="off" 时不设限，
        # 同一个人可以拿这个样本的多个模态。
        used = set()
        for modality in wanted:
            pool = _eligible(annotators=annotator_ids,
                             used=used if isolation == "strict" else set(),
                             load=load, per_annotator=per_annotator)
            if not pool:
                raise AllocationShortfall(
                    f"样本 {sample_id} 的 {modality} 无人可分："
                    f"{'隔离约束下已用尽' if isolation == 'strict' else ''}"
                    f"{'，或都到了 --per-annotator 上限' if per_annotator else ''}。"
                )
            # 先最闲的；同样闲就挑该模态做得最少的；再同分随机打破，避免固定偏向
            pick = min(pool, key=lambda a: (load[a], per_mod[a][modality], rng.random()))
            buckets[pick].append((sample_id, modality, is_anchor))
            used.add(pick)
            load[pick] += 1
            per_mod[pick][modality] += 1

    return dict(buckets)


def order_queue(rows, modalities, seed=0):
    """给一位标注者的子任务排队列顺序。

    **同一模态排在一起**——Yoe 定的：先标完所有音频，再所有面部，以免频繁切换
    造成认知混乱。模态块的先后按 `modalities` 给定的次序，与前端
    `taskFlow.ts` 的 MODALITY_ORDER 一致。

    锚点仍插进各自模态块的**内部**而非首尾，使其与普通子任务处于同等疲劳水平。
    """
    rng = random.Random(seed)
    by_mod = defaultdict(list)
    for sample_id, modality, is_anchor in rows:
        by_mod[modality].append((sample_id, is_anchor))

    queue = []
    for modality in modalities:
        block = by_mod.get(modality)
        if not block:
            continue
        base = [r for r in block if not r[1]]
        anchors = [r for r in block if r[1]]
        rng.shuffle(base)
        for anchor in anchors:
            position = rng.randrange(1, len(base)) if len(base) > 1 else len(base)
            base.insert(position, anchor)
        queue.extend((sample_id, modality, is_anchor) for sample_id, is_anchor in base)
    return queue


def build_plan(
    pool_ids,
    anchor_ids,
    annotator_ids,
    modalities,
    coverage=2,
    seed=0,
    per_annotator=0,
    isolation="strict",
):
    """产出完整分配计划，一行一个子任务。"""
    buckets = assign_subtasks(
        pool_ids, anchor_ids, annotator_ids, modalities,
        coverage=coverage, seed=seed,
        per_annotator=per_annotator, isolation=isolation,
    )
    rows = []
    for offset, annotator in enumerate(annotator_ids):
        queue = order_queue(buckets.get(annotator, []), modalities, seed + offset)
        rows.extend(
            PlanRow(annotator, order_index, sample_id, modality, is_anchor)
            for order_index, (sample_id, modality, is_anchor) in enumerate(queue)
        )
    return rows


def audit(rows, modalities):
    """给计划做体检，供 manage.py 打印。不做判断，只把事实摆出来。"""
    per_annotator = defaultdict(int)
    per_pair = defaultdict(set)
    per_mod = defaultdict(lambda: defaultdict(int))
    sample_annotators = defaultdict(set)
    sample_mod_count = defaultdict(lambda: defaultdict(int))

    for row in rows:
        per_annotator[row.annotator_id] += 1
        per_pair[row.annotator_id].add(row.sample_id)
        per_mod[row.annotator_id][row.modality] += 1
        sample_annotators[row.sample_id].add(row.annotator_id)
        sample_mod_count[row.sample_id][row.modality] += 1

    # 隔离是否被破坏：某人拿到同一样本的多个子任务
    violations = [
        a for a in per_annotator
        if per_annotator[a] != len(per_pair[a])
    ]
    loads = sorted(per_annotator.values())
    mod_spread = {
        m: sorted(per_mod[a][m] for a in per_annotator) for m in modalities
    }
    return {
        "rows": len(rows),
        "annotators": len(per_annotator),
        "samples": len(sample_annotators),
        "load_min": loads[0] if loads else 0,
        "load_max": loads[-1] if loads else 0,
        "isolation_violations": violations,
        "modality_min_max": {
            m: (v[0], v[-1]) if v else (0, 0) for m, v in mod_spread.items()
        },
    }
