from collections import Counter

import pytest

from app.allocation import build_plan, even_split, interleave, spread_anchors

POOL = [f"s{i:04d}" for i in range(3500)]
ANCHORS = POOL[:300]
ANNOTATORS = [f"P3-{i:02d}" for i in range(1, 21)]


def test_even_split_balances_within_one():
    buckets = even_split(POOL, ANNOTATORS, seed=1)
    sizes = sorted(len(v) for v in buckets.values())
    assert sizes[-1] - sizes[0] <= 1
    assert sum(sizes) == len(POOL)


def test_even_split_loses_no_sample_and_duplicates_none():
    buckets = even_split(POOL, ANNOTATORS, seed=1)
    dealt = [s for bucket in buckets.values() for s in bucket]
    assert sorted(dealt) == sorted(POOL)


def test_even_split_is_reproducible_from_the_seed():
    """同一 seed 必须重现同一分配，否则计划无法复核也无法回溯。"""
    assert even_split(POOL, ANNOTATORS, 7) == even_split(POOL, ANNOTATORS, 7)
    assert even_split(POOL, ANNOTATORS, 7) != even_split(POOL, ANNOTATORS, 8)


def test_each_anchor_reaches_distinct_annotators():
    """一个锚点落到同一人两次等于没有重叠，一致性就算不出来。"""
    buckets = spread_anchors(ANCHORS, ANNOTATORS, coverage=2, seed=1)
    for annotator, anchors in buckets.items():
        assert len(anchors) == len(set(anchors)), annotator

    seen = Counter(a for anchors in buckets.values() for a in anchors)
    assert set(seen.values()) == {2}


def test_anchor_load_is_balanced():
    buckets = spread_anchors(ANCHORS, ANNOTATORS, coverage=2, seed=1)
    sizes = sorted(len(v) for v in buckets.values())
    assert sizes[-1] - sizes[0] <= 1


def test_coverage_cannot_exceed_headcount():
    with pytest.raises(ValueError):
        spread_anchors(ANCHORS, ANNOTATORS[:2], coverage=3, seed=1)


def test_anchors_land_inside_the_queue_not_at_the_head():
    """锚点堆在开头或结尾会与正常样本处在不同疲劳水平，不可比。"""
    queue = interleave([f"b{i}" for i in range(50)], [f"a{i}" for i in range(10)], seed=3)
    assert queue[0][1] is False
    positions = [i for i, (_, is_anchor) in enumerate(queue) if is_anchor]
    assert min(positions) > 0
    assert max(positions) < len(queue) - 1


def test_plan_covers_the_whole_pool_exactly_once_outside_anchors():
    rows = build_plan(POOL, ANCHORS, ANNOTATORS, coverage=2, seed=11)
    regular = [r.sample_id for r in rows if not r.is_anchor]
    assert sorted(regular) == sorted(set(POOL) - set(ANCHORS))


def test_plan_queue_order_is_contiguous_per_annotator():
    """order_index 是队列顺序，必须从 0 连续，否则下发顺序会出洞。"""
    rows = build_plan(POOL, ANCHORS, ANNOTATORS, coverage=2, seed=11)
    by_annotator: dict[str, list[int]] = {}
    for row in rows:
        by_annotator.setdefault(row.annotator_id, []).append(row.order_index)
    for annotator, indices in by_annotator.items():
        assert sorted(indices) == list(range(len(indices))), annotator


def test_no_annotator_sees_the_same_sample_twice():
    rows = build_plan(POOL, ANCHORS, ANNOTATORS, coverage=2, seed=11)
    per_annotator: dict[str, list[str]] = {}
    for row in rows:
        per_annotator.setdefault(row.annotator_id, []).append(row.sample_id)
    for annotator, samples in per_annotator.items():
        assert len(samples) == len(set(samples)), annotator


def test_single_annotator_still_produces_a_usable_queue():
    rows = build_plan(POOL[:20], POOL[:5], ["solo"], coverage=1, seed=2)
    assert len(rows) == 20
    assert sum(1 for r in rows if r.is_anchor) == 5
