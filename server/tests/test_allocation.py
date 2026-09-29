"""子任务分配的测试（2026-09-29 版）。

不设锚点，全量重复：每个 (样本, 模态) 由 `coverage` 位不同的标注者各标一遍。
约束只有两条：
1. 同一个标注者不得拿到两次完全相同的 (样本, 模态)；同一视频的不同模态归同一个人是允许的
2. chsims 的 text 与 audiovisual 只分给中文标注者
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
from app.config import MODALITIES, ZH_ONLY_MODALITIES
from manage import zh_only_subtasks

# 数据集比例大致照真实池子（chsims 约 27%）
POOL = (
    [f"chsims_v{i:04d}" for i in range(160)]
    + [f"meld_dia{i}_utt0" for i in range(160)]
    + [f"iemocap_s{i:04d}" for i in range(160)]
    + [f"mosi_c{i:04d}" for i in range(120)]
)
ZH_ONLY = zh_only_subtasks(POOL)

# 阶段一：8 人，其中 2 位中文
STAGE1 = {
    "P1-EN-01": "en", "P1-EN-02": "en", "P1-EN-03": "en",
    "P1-EN-04": "en", "P1-EN-05": "en", "P1-EN-06": "en",
    "P1-ZH-01": "zh", "P1-ZH-02": "zh",
}
# 阶段二：10 人，其中 3 位中文
STAGE2 = {
    **{f"P2-EN-{i:02d}": "en" for i in range(1, 8)},
    **{f"P2-ZH-{i:02d}": "zh" for i in range(1, 4)},
}


def plan(**kw):
    args = dict(pool_ids=POOL, anchor_ids=[], annotator_languages=STAGE1,
                modalities=list(MODALITIES), zh_only=ZH_ONLY, coverage=2, seed=1)
    args.update(kw)
    return build_plan(**args)


def report_of(rows, languages=STAGE1, zh_only=ZH_ONLY):
    return audit(rows, list(MODALITIES), languages, zh_only)


# ----------------------------------------------------- 唯一的重复约束


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
    """同一视频的不同模态归同一个人完全可以（8 人排 10 个槽位，本来也必然发生）。"""
    seen = defaultdict(Counter)
    for row in plan():
        seen[row.annotator_id][row.sample_id] += 1
    assert any(
        any(n > 1 for n in counts.values()) for counts in seen.values()
    ), "一个跨模态重复都没有，说明约束比定稿口径更严"


def test_audit_catches_a_duplicate_subtask():
    """体检函数本身要能发现破口，否则它只是装饰。破口手工造。"""
    rows = [
        PlanRow("P1-EN-01", 0, "meld_dia1_utt0", "face", False),
        PlanRow("P1-EN-01", 1, "meld_dia1_utt0", "face", False),
        PlanRow("P1-EN-02", 0, "meld_dia1_utt0", "audio", False),
    ]
    assert report_of(rows)["duplicate_subtasks"] == ["P1-EN-01"]


def test_one_annotator_cannot_cover_a_subtask_twice():
    with pytest.raises(AllocationShortfall):
        plan(pool_ids=["meld_dia1_utt0"], annotator_languages={"P1-EN-01": "en"},
             modalities=["face"], zh_only=set())


def test_audit_reports_repeats_without_calling_them_violations():
    """跨模态重复要摆出来供判断污染面，但不算破口。"""
    report = report_of(plan())
    assert report["duplicate_subtasks"] == []
    assert report["repeat_samples"] > 0


# ----------------------------------------------------- 语言约束


def test_zh_only_subtasks_go_only_to_chinese_annotators():
    for row in plan():
        if (row.sample_id, row.modality) in ZH_ONLY:
            assert STAGE1[row.annotator_id] == "zh", row


def test_english_annotators_never_get_chsims_text_or_full():
    """英文标注者读不懂中文，chsims 的 text 与 full 一条都不能到他们手里。"""
    for row in plan():
        if STAGE1[row.annotator_id] == "en" and row.sample_id.startswith("chsims_"):
            assert row.modality not in ZH_ONLY_MODALITIES, row


def test_chsims_other_modalities_are_open_to_everyone():
    """face / body / audio 与语言无关，chsims 的这三个模态英文标注者照样能拿。"""
    got = {
        row.modality for row in plan()
        if STAGE1[row.annotator_id] == "en" and row.sample_id.startswith("chsims_")
    }
    assert got == {"face", "body", "audio"}


def test_two_chinese_annotators_at_coverage_two_take_every_zh_only_subtask():
    """阶段一的硬后果：中文人数正好等于覆盖度，每个中文专属子任务两人都要标。"""
    report = report_of(plan())
    for annotator in ("P1-ZH-01", "P1-ZH-02"):
        assert report["zh_only_load"][annotator] == len(ZH_ONLY)


def test_too_few_chinese_annotators_is_refused_up_front():
    """总人数够、中文不够，也要当场报错，而不是排到一半才发现。"""
    one_zh = {k: v for k, v in STAGE1.items() if k != "P1-ZH-02"}
    with pytest.raises(AllocationShortfall, match="中文"):
        plan(annotator_languages=one_zh)


def test_a_pool_without_chsims_needs_no_chinese_annotators():
    english_only = [s for s in POOL if not s.startswith("chsims_")]
    all_en = {f"P1-EN-{i:02d}": "en" for i in range(1, 5)}
    rows = plan(pool_ids=english_only, annotator_languages=all_en,
                zh_only=zh_only_subtasks(english_only))
    assert len(rows) == len(english_only) * len(MODALITIES) * 2


def test_phase_two_three_chinese_at_coverage_three():
    rows = plan(annotator_languages=STAGE2, coverage=3)
    report = report_of(rows, STAGE2)
    assert report["language_violations"] == 0
    assert report["duplicate_subtasks"] == []
    for annotator, language in STAGE2.items():
        if language == "zh":
            assert report["zh_only_load"][annotator] == len(ZH_ONLY)


def test_audit_flags_a_language_violation():
    rows = [PlanRow("P1-EN-01", 0, "chsims_v0001", "text", False)]
    assert report_of(rows)["language_violations"] == 1


# ----------------------------------------------------- 覆盖度


def test_every_subtask_is_covered_exactly_coverage_times():
    counts = defaultdict(Counter)
    for row in plan():
        counts[row.sample_id][row.modality] += 1
    for sample_id in POOL:
        got = counts[sample_id]
        assert set(got) == set(MODALITIES), f"{sample_id} 缺模态"
        assert all(n == 2 for n in got.values()), f"{sample_id} 份数不对：{dict(got)}"


def test_row_count_matches_the_redundancy_model():
    assert len(plan()) == len(POOL) * len(MODALITIES) * 2


def test_coverage_beyond_the_headcount_is_refused():
    with pytest.raises(AllocationShortfall):
        plan(coverage=9)


def test_per_annotator_cap_is_honoured_or_reported():
    with pytest.raises(AllocationShortfall):
        plan(per_annotator=10)


# ----------------------------------------------------- 均衡


def test_load_is_balanced_despite_the_forced_chinese_load():
    """中文标注者被硬塞了全部中文专属子任务，其余子任务要把大家填平。"""
    report = report_of(plan())
    assert report["load_max"] - report["load_min"] <= 2, report["per_annotator"]


def test_english_annotators_do_not_specialise_in_one_modality():
    """不能有人专做 face、另一人专做 text——那会把模态差异和标注者差异混在一起。
    中文标注者必然偏重 text/full（硬负载），只看英文组内部。"""
    per_mod = defaultdict(Counter)
    for row in plan():
        if STAGE1[row.annotator_id] == "en":
            per_mod[row.modality][row.annotator_id] += 1
    for modality, counts in per_mod.items():
        assert max(counts.values()) - min(counts.values()) <= 5, (modality, counts)


# ----------------------------------------------------- 队列顺序


def test_queue_groups_each_modality_together():
    """同一模态排在一起——先标完所有 face，再 body……避免频繁切换。"""
    rows = [(f"s{i:03d}", m, False) for m in MODALITIES for i in range(6)]
    queue = order_queue(rows, list(MODALITIES), seed=1)
    order = [m for _, m, _ in queue]
    runs = [m for i, m in enumerate(order) if i == 0 or order[i - 1] != m]
    assert runs == list(MODALITIES)


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
