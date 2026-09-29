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

## 中文标注者的英文定额

中文标注者也要标一部分**英文**的 text 与 full（`zh_open_quota`，阶段一每人每模态
200 条，Yoe 2026-09-29 定），这样才能量出中文组与英文组在同类材料上的系统差异。
不设定额的话，他们的 text/full 被 chsims 占满，算法按模态均衡一条英文的都不会给。
定额是**精确值**：排完定额后，这些模态的英文子任务不再分给中文标注者。

## 排法（三遍）

1. **中文专属**：中文标注者少（阶段一 2 位 × 覆盖度 2，正好满员），没有调度余地，
   是硬负载，最先落定
2. **中文定额**：从英文 text / full 里给每位中文标注者各发定额，每个子任务至多发一位，
   尽量铺到不同样本上
3. **其余**：用剩下的子任务把所有人往均值填平。反过来先排普通任务的话，中文标注者
   前面已经拿够，后面硬负载一压就会明显超出别人

每一步挑人：先挑当前最闲的；同样闲时看这个人该模态已有多少（避免有人专做 face、
有人专做 text）；再同分随机打破。
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
    zh_open_quota,
    coverage=2,
    seed=0,
    per_annotator=0,
):
    """把每个 (样本, 模态) 发给 `coverage` 位不同的标注者。

    `annotator_languages`：{annotator_id: "zh" | "en"}，迭代顺序即标注者顺序。
    `zh_only`：只能分给 zh 的 (sample_id, modality) 集合。
    `zh_open_quota`：{modality: n}，每位中文标注者在该模态上恰好拿 n 条**不在**
    `zh_only` 里的子任务；该模态的其余非专属子任务只给英文标注者。

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
    constrained = [st for st in subtasks if st in zh_only]
    open_ = [st for st in subtasks if st not in zh_only]

    # 定额为 0 也要留在表里：它的意思是「这个模态的英文子任务中文标注者一条不拿」
    quota = dict(zh_open_quota) if speakers_zh else {}
    for modality, n in quota.items():
        supply = sum(1 for st in open_ if st[1] == modality)
        if n * len(speakers_zh) > supply:
            raise AllocationShortfall(
                f"{modality} 的中文定额要 {n} × {len(speakers_zh)} 条非专属子任务，"
                f"但只有 {supply} 条。"
            )
    speakers_en = [a for a in annotators if annotator_languages[a] != "zh"]

    anchors = set(anchor_ids)
    buckets = defaultdict(list)
    load = {a: 0 for a in annotators}
    per_mod = {a: defaultdict(int) for a in annotators}
    taken = defaultdict(set)

    # 模态均衡的尺子：第三遍之前是「该模态已有几条」，第三遍换成「完成了应得份额的几成」
    fill = lambda a, modality: per_mod[a][modality]  # noqa: E731

    def give(subtask, candidates):
        sample_id, modality = subtask
        pool = [
            a for a in candidates
            if a not in taken[subtask]
            and not (per_annotator and load[a] >= per_annotator)
        ]
        if not pool:
            raise AllocationShortfall(
                f"样本 {sample_id} 的 {modality} 无人可分：合格者已用尽"
                f"{'，或都到了 --per-annotator 上限' if per_annotator else ''}。"
            )
        pick = min(pool, key=lambda a: (load[a], fill(a, modality), rng.random()))
        buckets[pick].append((sample_id, modality, sample_id in anchors))
        taken[subtask].add(pick)
        load[pick] += 1
        per_mod[pick][modality] += 1
        return pick

    # 第一遍：中文专属，硬负载
    for subtask in constrained:
        for _ in range(coverage):
            give(subtask, speakers_zh)

    # 第二遍：中文定额。每个子任务至多给一位，发给定额还差得最多的那位
    owed = {(a, m): n for m, n in quota.items() for a in speakers_zh}
    for subtask in open_:
        modality = subtask[1]
        if modality not in quota:
            continue
        needy = [a for a in speakers_zh if owed[(a, modality)] > 0]
        if not needy:
            continue
        most = max(owed[(a, modality)] for a in needy)
        pick = give(subtask, [a for a in needy if owed[(a, modality)] == most])
        owed[(pick, modality)] -= 1

    # 第三遍：其余。定额模态的英文子任务不再给中文标注者，定额才是精确值
    def eligible(modality):
        return speakers_en if modality in quota else annotators

    share = _fair_shares(open_, coverage, taken, load, per_mod, modalities, eligible)
    fill = lambda a, modality: (  # noqa: E731
        per_mod[a][modality] / share[a][modality] if share[a][modality] > 0 else float("inf")
    )
    for subtask in open_:
        while len(taken[subtask]) < coverage:
            give(subtask, eligible(subtask[1]))

    return dict(buckets)


def _fair_shares(open_, coverage, taken, load, per_mod, modalities, eligible):
    """第三遍开始前，算每人每模态「最终应得多少条」。

    为什么要算：按绝对条数拉平各模态时，剩余容量小的人（中文标注者，前两遍已拿走
    一大半）会先被 face 拉到和别人一样多，排在后面的 audio 就被挤没了——试排出过
    face 854 / body 579 / audio 414。改成按份额比例拉平，每人各模态的完成度同步上涨。

    份额：每人总量拉到均值；定额模态的剩余英文子任务在合格者之间均分；
    其余容量按各模态剩余量的比例分到其余模态上。
    """
    remaining = defaultdict(int)
    for subtask in open_:
        remaining[subtask[1]] += coverage - len(taken[subtask])
    people = list(load)
    total = sum(load.values()) + sum(remaining.values())
    target = total / len(people)

    share = {a: {m: float(per_mod[a][m]) for m in modalities} for a in people}
    restricted = [m for m in modalities if set(eligible(m)) != set(people)]
    shared = [m for m in modalities if m not in restricted]
    capacity = {a: target - load[a] for a in people}
    for modality in restricted:
        group = eligible(modality)
        for a in group:
            share[a][modality] += remaining[modality] / len(group)
            capacity[a] -= remaining[modality] / len(group)
    pool = sum(remaining[m] for m in shared)
    for a in people:
        for modality in shared:
            if pool:
                share[a][modality] += max(capacity[a], 0) * remaining[modality] / pool
    return share


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
    zh_open_quota,
    coverage=2,
    seed=0,
    per_annotator=0,
):
    """产出完整分配计划，一行一个子任务。"""
    buckets = assign_subtasks(
        pool_ids, anchor_ids, annotator_languages, modalities, zh_only, zh_open_quota,
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
    # 每人每模态再按「中文专属 / 非专属」拆开：中文标注者的英文定额就在这里看
    mix = defaultdict(lambda: defaultdict(int))
    language_violations = []

    for row in rows:
        per_annotator[row.annotator_id] += 1
        per_subtask[row.annotator_id][(row.sample_id, row.modality)] += 1
        per_sample_times[row.annotator_id][row.sample_id] += 1
        per_mod[row.annotator_id][row.modality] += 1
        sample_annotators[row.sample_id].add(row.annotator_id)
        exclusive = (row.sample_id, row.modality) in zh_only
        mix[row.annotator_id][(row.modality, exclusive)] += 1
        if exclusive:
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
        "mix": {a: dict(mix[a]) for a in per_annotator},
        "duplicate_subtasks": duplicates,
        "language_violations": len(language_violations),
        "repeat_samples": repeats,
        "modality_min_max": {
            m: (v[0], v[-1]) if v else (0, 0) for m, v in mod_spread.items()
        },
    }
