"""子任务分配的测试（2026-09-21 口径）。

不设锚点，全量重复：每个 (样本, 模态) 由 `coverage` 位标注者各标一遍。
**唯一的隔离约束是「同一个标注者不得拿到两次完全相同的 (样本, 模态)」**——
同一个视频的不同模态归同一个人是允许的。

从前那套硬隔离（一个样本的各模态必须分给不同的人）已经废弃，
`strict` 只作为历史选项保留；`off` 连重复子任务都不拦，仅用于制造破口。
"""
from collections import Counter, defaultdict

import pytest

from app.allocation import (
    AllocationShortfall,
    PlanRow,
    audit,
    build_plan,
    order_queue,
)
from app.config import MODALITIES

POOL = [f"s{i:04d}" for i in range(600)]
ANNOTATORS = [f"P3-{i:02d}" for i in range(1, 9)]  # 阶段一：8 人


def plan(**kw):
    args = dict(pool_ids=POOL, anchor_ids=[], annotator_ids=ANNOTATORS,
                modalities=list(MODALITIES), coverage=2, seed=1)
    args.update(kw)
    return build_plan(**args)


# ----------------------------------------------------- 唯一要禁的那件事


def test_nobody_gets_the_same_subtask_twice():
    """同一人标两遍一模一样的子任务，等于这条只被标了一遍，
    而进度表上算两遍——数据看起来毫无异样，所以必须在分配时就拦住。"""
    seen = defaultdict(Counter)
    for row in plan():
        seen[row.annotator_id][(row.sample_id, row.modality)] += 1
    for annotator, counts in seen.items():
        dupes = [key for key, n in counts.items() if n > 1]
        assert not dupes, f"{annotator} 拿到重复子任务 {dupes[:3]}"


def test_one_person_may_take_several_modalities_of_a_video():
    """Yoe 2026-09-21 定的：同一视频的不同模态归同一个人完全可以。
    8 人排 10 个槽位，本来也必然发生。"""
    seen = defaultdict(Counter)
    for row in plan():
        seen[row.annotator_id][row.sample_id] += 1
    assert any(
        any(n > 1 for n in counts.values()) for counts in seen.values()
    ), "一个跨模态重复都没有，说明约束比定稿口径更严"


def test_audit_catches_a_duplicate_subtask():
    """体检函数本身要能发现破口，否则它只是装饰。

    破口这里是手工造的：`isolation="off"` 虽然不拦重复，负载均衡也几乎
    不会真的挑中同一个人两次（第一次挑完他的负载就涨了）。体检要能认出
    这种破口，不能指望它在正常分配里自然出现。
    """
    rows = [
        PlanRow("P3-01", 0, "s0001", "face", False),
        PlanRow("P3-01", 1, "s0001", "face", False),
        PlanRow("P3-02", 0, "s0001", "audio", False),
    ]
    assert audit(rows, list(MODALITIES))["duplicate_subtasks"] == ["P3-01"]


def test_off_mode_does_not_guard_against_duplicates():
    """一个人、覆盖度 2：off 只能把两份都给他，subtask 会当场报错。"""
    rows = build_plan(pool_ids=["s1"], anchor_ids=[], annotator_ids=["P3-01"],
                      modalities=["face"], coverage=2, seed=1, isolation="off")
    assert len(rows) == 2
    assert audit(rows, ["face"])["duplicate_subtasks"] == ["P3-01"]
    with pytest.raises(AllocationShortfall):
        build_plan(pool_ids=["s1"], anchor_ids=[], annotator_ids=["P3-01"],
                   modalities=["face"], coverage=2, seed=1, isolation="subtask")


def test_audit_reports_repeats_without_calling_them_violations():
    """跨模态重复要摆出来供判断污染面，但不算破口。"""
    report = audit(plan(), list(MODALITIES))
    assert report["duplicate_subtasks"] == []
    assert report["repeat_samples"] > 0


def test_isolation_rejects_an_unknown_mode():
    with pytest.raises(ValueError):
        plan(isolation="loose")


# ----------------------------------------------------- 覆盖度


def test_every_subtask_is_covered_exactly_coverage_times():
    """全量重复：**每条**样本的每个模态都要 coverage 份。
    从前是「普通样本 1 份、只有锚点 coverage 份」，那套已废弃。"""
    counts = defaultdict(Counter)
    for row in plan():
        counts[row.sample_id][row.modality] += 1
    for sample_id in POOL:
        got = counts[sample_id]
        assert set(got) == set(MODALITIES), f"{sample_id} 缺模态"
        assert all(n == 2 for n in got.values()), f"{sample_id} 份数不对：{dict(got)}"


def test_coverage_three_is_the_phase_two_setting():
    counts = defaultdict(Counter)
    for row in plan(coverage=3, annotator_ids=[f"P3-{i:02d}" for i in range(1, 11)]):
        counts[row.sample_id][row.modality] += 1
    assert all(n == 3 for got in counts.values() for n in got.values())


def test_row_count_matches_the_redundancy_model():
    assert len(plan()) == len(POOL) * len(MODALITIES) * 2


def test_coverage_beyond_the_headcount_is_refused():
    """4 个人排不出「每个子任务 5 位不同的人」，必须当场报错。
    偷偷少发几条的话，要等分析时才发现某些子任务只有两份。"""
    with pytest.raises(AllocationShortfall):
        plan(coverage=5, annotator_ids=ANNOTATORS[:4])


def test_per_annotator_cap_is_honoured_or_reported():
    with pytest.raises(AllocationShortfall):
        plan(per_annotator=10)


# ----------------------------------------------------- 均衡


def test_load_is_balanced_within_a_few():
    report = audit(plan(), list(MODALITIES))
    assert report["load_max"] - report["load_min"] <= 5


def test_no_annotator_specialises_in_one_modality():
    """不能有人专做 face、另一人专做 text——那会把模态差异和标注者差异混在一起。"""
    report = audit(plan(), list(MODALITIES))
    for modality, (lo, hi) in report["modality_min_max"].items():
        assert hi - lo <= 5, f"{modality} 的人均条数差得太远：{lo}..{hi}"


# ----------------------------------------------------- 队列顺序


def test_queue_groups_each_modality_together():
    """同一模态排在一起——先标完所有音频，再所有面部，避免频繁切换。"""
    rows = [(f"s{i:03d}", m, False) for m in MODALITIES for i in range(6)]
    queue = order_queue(rows, list(MODALITIES), seed=1)
    order = [m for _, m, _ in queue]
    runs = [m for i, m in enumerate(order) if i == 0 or order[i - 1] != m]
    assert runs == [m for m in MODALITIES]


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


# ----------------------------------------------------- 废弃的 strict


def test_strict_still_works_for_the_old_paradigm():
    """保留但已废弃。人手够时仍应排得出同一样本各模态归不同人的计划。"""
    rows = plan(isolation="strict", coverage=1,
                annotator_ids=[f"P3-{i:02d}" for i in range(1, 11)])
    seen = defaultdict(list)
    for row in rows:
        seen[row.annotator_id].append(row.sample_id)
    for samples in seen.values():
        assert len(samples) == len(set(samples))
