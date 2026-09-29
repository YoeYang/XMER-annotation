"""子任务分配计划（2026-09-29 版）。

分配以**子任务**为单位（样本 × 模态）。每个 (样本, 模态) 由 `coverage` 位不同的
标注者各标一遍（阶段一 2 遍、阶段二 3 遍），不设锚点，全量重复。

## 约束只有两条

1. **同一个标注者不得拿到两次完全相同的 (样本, 模态)**。同一人标两遍一模一样的
   子任务，等于这条只被标了一遍，而进度表上算两遍——数据看起来毫无异样。
   除此之外全部打乱：同一视频的不同模态**可以**归同一个人，也可以不归。
   （「同一样本各模态分给不同的人」的硬隔离 Yoe 已两次否决，不要加回。）
2. **语言**：`zh_only` 里的子任务只能分给 `zh` 标注者（chsims 的 text 与
   audiovisual，要读懂中文）。其余子任务不限语言。

## 排法

* **受语言约束的子任务先排**。中文标注者少（阶段一 2 位 × 覆盖度 2，正好满员），
  这批子任务没有调度余地，是硬负载。先把它落定，再用不受约束的子任务把所有人
  往均值填平；反过来排的话，中文标注者前面已经拿够了普通任务，后面硬负载一压
  就会明显超出别人。
* **负载**：每次从合格者里挑当前最闲的
* **模态均衡**：同样闲时看这个人该模态已有多少，避免有人专做 face、有人专做 text
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

    与其偷偷少发几条（分析时才发现某些子任务只有一份），不如当场报错，
    并把缺口说清楚：要么加人，要么降 coverage。
    """


def assign_subtasks(
    pool_ids,
    anchor_ids,
    annotator_languages,
    modalities,
    zh_only,
    coverage=2,
    seed=0,
    per_annotator=0,
):
    """把每个 (样本, 模态) 发给 `coverage` 位不同的标注者。

    `annotator_languages`：{annotator_id: "zh" | "en"}，迭代顺序即标注者顺序。
    `zh_only`：只能分给 zh 的 (sample_id, modality) 集合。

    返回 {annotator_id: [(sample_id, modality, is_anchor), ...]}，顺序未定，
    队列顺序由 `order_queue()` 另行安排。
    """
    annotators = list(annotator_languages)
    if not annotators:
        raise ValueError("至少需要一位标注者")
    if not modalities:
        raise ValueError("至少需要一个模态")
    if coverage < 1:
        raise ValueError("覆盖度至少为 1")

    speakers_zh = [a for a in annotators if annotator_languages[a] == "zh"]
    if coverage > len(annotators):
        raise AllocationShortfall(
            f"一个 (样本, 模态) 要 {coverage} 位不同的标注者，"
            f"但只有 {len(annotators)} 位。加人或降 coverage。"
        )
    needs_zh = any((s, m) in zh_only for s in pool_ids for m in modalities)
    if needs_zh and coverage > len(speakers_zh):
        raise AllocationShortfall(
            f"只能给中文标注者的子任务要 {coverage} 位不同的中文标注者，"
            f"但只有 {len(speakers_zh)} 位。加中文标注者或降 coverage。"
        )

    rng = random.Random(seed)
    order = list(pool_ids)
    rng.shuffle(order)
    subtasks = [(s, m) for s in order for m in modalities]
    # 受约束的先排，见模块说明
    constrained = [st for st in subtasks if st in zh_only]
    free = [st for st in subtasks if st not in zh_only]

    anchors = set(anchor_ids)
    buckets = defaultdict(list)
    load = {a: 0 for a in annotators}
    per_mod = {a: defaultdict(int) for a in annotators}

    work = [(st, speakers_zh) for st in constrained] + [(st, annotators) for st in free]
    for (sample_id, modality), candidates in work:
        taken = set()
        for _ in range(coverage):
            pool = [
                a for a in candidates
                if a not in taken
                and not (per_annotator and load[a] >= per_annotator)
            ]
            if not pool:
                raise AllocationShortfall(
                    f"样本 {sample_id} 的 {modality} 无人可分："
                    f"合格者已用尽"
                    f"{'，或都到了 --per-annotator 上限' if per_annotator else ''}。"
                )
            # 先最闲的；同样闲就挑该模态做得最少的；再同分随机打破，避免固定偏向
            pick = min(pool, key=lambda a: (load[a], per_mod[a][modality], rng.random()))
            buckets[pick].append((sample_id, modality, sample_id in anchors))
            taken.add(pick)
            load[pick] += 1
            per_mod[pick][modality] += 1

    return dict(buckets)


def order_queue(rows, modalities, seed=0):
    """给一位标注者的子任务排队列顺序。

    **同一模态排在一起**——Yoe 定的：先标完所有 face，再 body……以免频繁切换
    造成认知混乱。模态块的先后按 `modalities` 给定的次序，与前端
    `taskFlow.ts` 的 MODALITY_ORDER 一致。块内随机。

    锚点插进各自模态块的**内部**而非首尾，使其与普通子任务处于同等疲劳水平。
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
    annotator_languages,
    modalities,
    zh_only,
    coverage=2,
    seed=0,
    per_annotator=0,
):
    """产出完整分配计划，一行一个子任务。"""
    buckets = assign_subtasks(
        pool_ids, anchor_ids, annotator_languages, modalities, zh_only,
        coverage=coverage, seed=seed, per_annotator=per_annotator,
    )
    rows = []
    for offset, annotator in enumerate(annotator_languages):
        queue = order_queue(buckets.get(annotator, []), modalities, seed + offset)
        rows.extend(
            PlanRow(annotator, order_index, sample_id, modality, is_anchor)
            for order_index, (sample_id, modality, is_anchor) in enumerate(queue)
        )
    return rows


def audit(rows, modalities, annotator_languages, zh_only):
    """给计划做体检，供 manage.py 打印。不做判断，只把事实摆出来。"""
    per_annotator = defaultdict(int)
    per_subtask = defaultdict(lambda: defaultdict(int))
    per_sample_times = defaultdict(lambda: defaultdict(int))
    per_mod = defaultdict(lambda: defaultdict(int))
    sample_annotators = defaultdict(set)
    zh_only_load = defaultdict(int)
    language_violations = []

    for row in rows:
        per_annotator[row.annotator_id] += 1
        per_subtask[row.annotator_id][(row.sample_id, row.modality)] += 1
        per_sample_times[row.annotator_id][row.sample_id] += 1
        per_mod[row.annotator_id][row.modality] += 1
        sample_annotators[row.sample_id].add(row.annotator_id)
        if (row.sample_id, row.modality) in zh_only:
            zh_only_load[row.annotator_id] += 1
            if annotator_languages.get(row.annotator_id) != "zh":
                language_violations.append(row)

    # 唯一要禁的破口：某人拿到两次完全相同的 (样本, 模态)。
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
        "per_annotator": dict(per_annotator),
        "zh_only_load": {a: zh_only_load.get(a, 0) for a in per_annotator},
        "duplicate_subtasks": duplicates,
        "language_violations": len(language_violations),
        "repeat_samples": repeats,
        "modality_min_max": {
            m: (v[0], v[-1]) if v else (0, 0) for m, v in mod_spread.items()
        },
    }
