"""子任务分配的测试。

V3 起分配以子任务（样本 × 模态）为单位，核心是**硬隔离**：
一个标注者拿到的子任务，样本互不重复。这批测试的重点就是把这条钉死——
它一旦被破坏，同一个人会把一段素材看四五遍，记忆污染拉满，而数据上看不出来。
"""
from collections import Counter, defaultdict

import pytest

from app.allocation import (
    AllocationShortfall,
    assign_subtasks,
    audit,
    build_plan,
    order_queue,
)
from app.config import MODALITIES

POOL = [f"s{i:04d}" for i in range(600)]
ANCHORS = POOL[:40]
ANNOTATORS = [f"P3-{i:02d}" for i in range(1, 21)]


def plan(**kw):
    args = dict(pool_ids=POOL, anchor_ids=ANCHORS, annotator_ids=ANNOTATORS,
                modalities=list(MODALITIES), coverage=2, seed=1)
    args.update(kw)
    return build_plan(**args)


# ------------------------------------------------------------- 隔离

def test_nobody_sees_the_same_sample_twice():
    """硬隔离的定义。破了它，同一个人就会把一段素材看好几遍。"""
    seen = defaultdict(list)
    for row in plan():
        seen[row.annotator_id].append(row.sample_id)
    for annotator, samples in seen.items():
        dupes = [s for s, n in Counter(samples).items() if n > 1]
        assert not dupes, f"{annotator} 重复见到样本 {dupes[:3]}"


def test_each_sample_modality_goes_to_distinct_annotators():
    """普通样本 5 个模态 → 5 个不同的人；锚点 5×2 → 10 个不同的人。"""
    by_sample = defaultdict(list)
    for row in plan():
        by_sample[row.sample_id].append(row.annotator_id)
    for sample_id, annotators in by_sample.items():
        assert len(annotators) == len(set(annotators)), f"{sample_id} 有人拿了两份"


def test_isolation_off_allows_one_person_to_take_several_modalities():
    """关掉隔离是明确的选项（小范围试标可能想这样），得真的能关。"""
    rows = plan(isolation="off", seed=3)
    seen = defaultdict(list)
    for row in rows:
        seen[row.annotator_id].append(row.sample_id)
    assert any(
        any(n > 1 for n in Counter(samples).values()) for samples in seen.values()
    )


def test_isolation_rejects_an_unknown_mode():
    with pytest.raises(ValueError):
        plan(isolation="loose")


# ------------------------------------------------------------- 覆盖度

def test_every_sample_gets_every_modality():
    counts = defaultdict(Counter)
    for row in plan():
        counts[row.sample_id][row.modality] += 1
    for sample_id in POOL:
        got = counts[sample_id]
        assert set(got) == set(MODALITIES), f"{sample_id} 缺模态 {set(MODALITIES)-set(got)}"


def test_anchors_are_covered_twice_and_others_once():
    """冗余口径：普通样本 1 份，只有锚点是 coverage 份。别记成每条都标多遍。"""
    counts = defaultdict(Counter)
    for row in plan():
        counts[row.sample_id][row.modality] += 1
    for sample_id in ANCHORS:
        assert all(n == 2 for n in counts[sample_id].values())
    for sample_id in POOL[len(ANCHORS):]:
        assert all(n == 1 for n in counts[sample_id].values())


def test_anchor_flag_marks_exactly_the_anchor_rows():
    flagged = {r.sample_id for r in plan() if r.is_anchor}
    assert flagged == set(ANCHORS)


def test_shortfall_is_raised_when_people_run_out():
    """9 个人排不出「锚点要 10 个不同的人」，必须当场报错。

    偷偷少发几条的话，分析时才会发现某些样本只有两个模态——那时已经标完了。
    """
    with pytest.raises(AllocationShortfall):
        plan(annotator_ids=ANNOTATORS[:9])


def test_per_annotator_cap_is_honoured_or_reported():
    """给了上限就不能超；排不下要报错而不是悄悄截断。"""
    with pytest.raises(AllocationShortfall):
        plan(per_annotator=10)


# ------------------------------------------------------------- 均衡

def test_load_is_balanced_within_a_few():
    report = audit(plan(), list(MODALITIES))
    assert report["load_max"] - report["load_min"] <= 5


def test_no_annotator_specialises_in_one_modality():
    """不能有人专做 face、另一人专做 text——那会把模态差异和标注者差异混在一起。"""
    report = audit(plan(), list(MODALITIES))
    for modality, (lo, hi) in report["modality_min_max"].items():
        assert hi - lo <= 5, f"{modality} 的人均条数差得太远：{lo}..{hi}"


def test_audit_catches_a_broken_isolation():
    """体检函数本身要能发现问题，否则它只是装饰。"""
    rows = plan(isolation="off", seed=5)
    assert audit(rows, list(MODALITIES))["isolation_violations"]


# ------------------------------------------------------------- 队列顺序

def test_queue_groups_each_modality_together():
    """同一模态排在一起——先标完所有音频，再所有面部，避免频繁切换。"""
    rows = [(f"s{i:03d}", m, False) for m in MODALITIES for i in range(6)]
    queue = order_queue(rows, list(MODALITIES), seed=1)
    order = [m for _, m, _ in queue]
    # 每个模态只应出现一个连续段
    runs = [m for i, m in enumerate(order) if i == 0 or order[i - 1] != m]
    assert runs == [m for m in MODALITIES]


def test_queue_puts_anchors_inside_their_block_not_at_the_edges():
    """锚点排在块首或块尾，疲劳水平就和普通子任务不同了，一致性会被污染。"""
    rows = [("base%02d" % i, "audio", False) for i in range(20)]
    rows += [("anchor", "audio", True)]
    queue = order_queue(rows, ["audio"], seed=2)
    at = [i for i, (s, _, _) in enumerate(queue) if s == "anchor"][0]
    assert 0 < at < len(queue) - 1


def test_plan_is_reproducible_from_the_seed():
    """同一 seed 必须重现同一计划，否则计划无法复核也无法回溯。"""
    assert plan(seed=7) == plan(seed=7)
    assert plan(seed=7) != plan(seed=8)


def test_order_index_is_contiguous_per_annotator():
    by_annotator = defaultdict(list)
    for row in plan():
        by_annotator[row.annotator_id].append(row.order_index)
    for annotator, idxs in by_annotator.items():
        assert sorted(idxs) == list(range(len(idxs))), f"{annotator} 的队列序号有洞"


# ------------------------------------------------------------- 规模

def test_row_count_matches_the_redundancy_model():
    rows = plan()
    expect = (len(POOL) - len(ANCHORS)) * len(MODALITIES) \
        + len(ANCHORS) * len(MODALITIES) * 2
    assert len(rows) == expect
