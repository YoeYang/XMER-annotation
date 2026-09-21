"""子任务分配计划。

V3 起分配以**子任务**为单位（样本 × 模态），不再以样本为单位。

## 为什么改粒度

V2 时一行一个样本，**一个样本的所有模态全归同一个标注者**。到了 V3 这是最弱的
隔离——同一个人先看脸、再看身体、再听音频、再读文本，同一段素材看四五遍，
记忆污染拉满。Yoe 定的口径是**硬隔离**：一个标注者拿到的子任务，样本互不重复。

## 冗余口径（2026-09-21 定稿，与此前完全不同）

**不设锚点，全量重复**：每个 (样本, 模态) 由 `coverage` 位标注者各标一遍，
阶段一 2 遍、阶段二 3 遍。从前那套「普通样本 1 遍、只有锚点 coverage 遍」
已经废弃——现在 `coverage` 对**所有**样本生效。

## 唯一的隔离约束

**同一个标注者不得拿到两次完全相同的 (样本, 模态)**（`isolation="subtask"`，
默认）。除此之外不设限：同一个视频的不同模态归同一个人**完全可以**，
完整视频与某个单模态归同一个人也可以。

V3 最初设计的 `strict`（一个样本的各模态必须分给不同的人）**保留但已废弃**，
人数与覆盖度的算术排不出来。`off` 连同一个 (样本, 模态) 的重复都不拦，
只在刻意制造破口的测试里用。

## 另外两条

* **负载**：每次从合格者里挑当前最闲的
* **模态均衡**：同分时看这个人该模态已有多少，避免有人专做 face、有人专做 text
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


ISOLATION_MODES = ("subtask", "strict", "off")


def assign_subtasks(
    pool_ids,
    anchor_ids,
    annotator_ids,
    modalities,
    coverage=2,
    seed=0,
    per_annotator=0,
    isolation="subtask",
):
    """把每个 (样本, 模态) 发给 `coverage` 位标注者。

    返回 {annotator_id: [(sample_id, modality, is_anchor), ...]}，顺序未定，
    队列顺序由 `order_queue()` 另行安排。
    """
    if not annotator_ids:
        raise ValueError("至少需要一位标注者")
    if not modalities:
        raise ValueError("至少需要一个模态")
    if coverage < 1:
        raise ValueError("覆盖度至少为 1")
    if isolation not in ISOLATION_MODES:
        raise ValueError(f"isolation 只能是 {'、'.join(ISOLATION_MODES)}")

    anchors = set(anchor_ids)
    if isolation == "subtask" and coverage > len(annotator_ids):
        raise AllocationShortfall(
            f"一个 (样本, 模态) 要 {coverage} 位不同的标注者，"
            f"但只有 {len(annotator_ids)} 位。加人或降 coverage。"
        )
    if isolation == "strict":
        need = len(modalities) * coverage
        if need > len(annotator_ids):
            raise AllocationShortfall(
                f"硬隔离下一个样本需要 {need} 位不同的标注者"
                f"（{len(modalities)} 模态 × 覆盖度 {coverage}），"
                f"但只有 {len(annotator_ids)} 位。加人、降 coverage，或改用 subtask。"
            )

    rng = random.Random(seed)
    order = list(pool_ids)
    rng.shuffle(order)

    buckets = defaultdict(list)
    load = {a: 0 for a in annotator_ids}
    per_mod = {a: defaultdict(int) for a in annotator_ids}

    for sample_id in order:
        is_anchor = sample_id in anchors
        # 整个样本上已经用掉的人，只有 strict 拿它当禁区
        used_sample = set()
        for modality in modalities:
            # 这个 (样本, 模态) 上已经用掉的人。**默认模式唯一的禁区**：
            # 同一个人标两遍一模一样的子任务，等于这条只被标了一遍，
            # 而进度表上算两遍——数据看起来毫无异样。
            used_subtask = set()
            for _ in range(coverage):
                blocked = (
                    used_sample if isolation == "strict"
                    else used_subtask if isolation == "subtask"
                    else set()
                )
                pool = _eligible(annotators=annotator_ids, used=blocked,
                                 load=load, per_annotator=per_annotator)
                if not pool:
                    raise AllocationShortfall(
                        f"样本 {sample_id} 的 {modality} 无人可分："
                        f"{'隔离约束下已用尽' if isolation != 'off' else ''}"
                        f"{'，或都到了 --per-annotator 上限' if per_annotator else ''}。"
                    )
                # 先最闲的；同样闲就挑该模态做得最少的；再同分随机打破，避免固定偏向
                pick = min(pool,
                           key=lambda a: (load[a], per_mod[a][modality], rng.random()))
                buckets[pick].append((sample_id, modality, is_anchor))
                used_sample.add(pick)
                used_subtask.add(pick)
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
    isolation="subtask",
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
    per_subtask = defaultdict(lambda: defaultdict(int))
    per_sample_times = defaultdict(lambda: defaultdict(int))
    per_mod = defaultdict(lambda: defaultdict(int))
    sample_annotators = defaultdict(set)
    sample_mod_count = defaultdict(lambda: defaultdict(int))

    for row in rows:
        per_annotator[row.annotator_id] += 1
        per_subtask[row.annotator_id][(row.sample_id, row.modality)] += 1
        per_sample_times[row.annotator_id][row.sample_id] += 1
        per_mod[row.annotator_id][row.modality] += 1
        sample_annotators[row.sample_id].add(row.annotator_id)
        sample_mod_count[row.sample_id][row.modality] += 1

    # 唯一要禁的破口：某人拿到两次完全相同的 (样本, 模态)。
    # 拿到同一样本的不同模态是允许的，不算破口。
    duplicates = [
        annotator for annotator, seen in per_subtask.items()
        if any(n > 1 for n in seen.values())
    ]
    # 同一样本被同一人看过几次（不是破口，但要摆出来供判断污染面）
    repeats = sum(
        n - 1 for seen in per_sample_times.values() for n in seen.values() if n > 1
    )
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
        "duplicate_subtasks": duplicates,
        "repeat_samples": repeats,
        "modality_min_max": {
            m: (v[0], v[-1]) if v else (0, 0) for m, v in mod_spread.items()
        },
    }
