"""隐藏锚点：参考账号补标的队列（2026-10-01 版）。"""
import random
from collections import Counter
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

import manage
from app.anchors import anchor_candidates, pick_anchor_queue
from app.config import MODALITIES
from app.models import Annotator, Assignment, Attempt, Submission, Task

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
PEOPLE = [f"P1-EN-{i:02d}" for i in range(1, 8)] + [f"P1-ZH-{i:02d}" for i in range(1, 4)]


def synthetic(n=600, seed=1):
    rng = random.Random(seed)
    owners, modality_of = {}, {}
    for i in range(n):
        tid = f"S{i:04d}::{MODALITIES[i % 5]}"
        owners[tid] = rng.sample(PEOPLE, 2)
        modality_of[tid] = MODALITIES[i % 5]
    return owners, modality_of


def test_every_prefix_is_balanced_across_annotators():
    owners, modality_of = synthetic()
    queue = pick_anchor_queue(owners, modality_of, 300)
    assert len(queue) == len(set(queue)) == 300
    for k in (20, 50, 100, 200, 300):
        load = Counter(a for t in queue[:k] for a in owners[t])
        counts = [load[p] for p in PEOPLE]
        assert max(counts) - min(counts) <= 2, (k, counts)


def test_modalities_take_turns():
    owners, modality_of = synthetic()
    queue = pick_anchor_queue(owners, modality_of, 50)
    for start in range(0, 50, 5):
        assert [modality_of[t] for t in queue[start:start + 5]] == list(MODALITIES)


def test_small_pool_returns_everything():
    owners, modality_of = synthetic(n=12)
    assert sorted(pick_anchor_queue(owners, modality_of, 300)) == sorted(owners)


def test_same_seed_same_queue():
    owners, modality_of = synthetic()
    assert pick_anchor_queue(owners, modality_of, 100, 7) == pick_anchor_queue(owners, modality_of, 100, 7)


# ------------------------------------------------------------ 库里取候选、写入


def add_task(session, tid, modality="face"):
    session.add(Task(task_id=tid, media_id=tid, source_id=tid.split("::")[0], title=tid,
                     modality=modality, src="/x", duration=4.0))


@pytest.fixture
def world(session: Session):
    for aid, phase in [("P1-EN-01", "main"), ("P1-ZH-01", "main"), ("P2-EN-01", "main"),
                       ("ADMIN-EN-01", "main"), ("REF-01", "pilot"), ("REF-02", "pilot")]:
        session.add(Annotator(annotator_id=aid, token_hash=aid, phase=phase, language="zh"))
    for tid in ["S1::face", "S2::face", "S3::face", "S4::face", "S5::face"]:
        add_task(session, tid)
    session.flush()
    rows = [("P1-EN-01", "S1::face", "main"), ("P1-ZH-01", "S1::face", "main"),
            ("P1-EN-01", "S2::face", "main"), ("P1-ZH-01", "S3::face", "main"),
            ("P1-EN-01", "S3::face", "training"),             # 训练子任务：看过参考
            ("P1-ZH-01", "S4::face", "main"),                 # REF-01 已交过
            ("P2-EN-01", "S5::face", "main"),                 # 别的阶段
            ("ADMIN-EN-01", "S5::face", "main"),              # 镜像号不算
            ("REF-01", "S4::face", "pilot")]
    for i, (aid, tid, phase) in enumerate(rows):
        session.add(Assignment(annotator_id=aid, task_id=tid, phase=phase, order_index=i))
    session.add(Attempt(attempt_id="r1", task_id="S4::face", annotator_id="REF-01",
                        media_id="S4::face", modality="face", mode="annotation",
                        dimension="valence", status="completed", task_snapshot={},
                        events=[], sample_rate_hz=10, started_at=NOW))
    session.flush()
    session.add(Submission(submission_id="r1", task_id="S4::face", annotator_id="REF-01",
                           attempt_id="r1", dimension="valence", revision=1, submitted_at=NOW))
    session.commit()
    return session


def test_candidates_skip_training_reference_and_other_stages(world):
    owners, modality_of = anchor_candidates(world, 1)
    assert owners == {"S1::face": ["P1-EN-01", "P1-ZH-01"], "S2::face": ["P1-EN-01"]}
    assert modality_of == {"S1::face": "face", "S2::face": "face"}


def run(session, **kw):
    args = SimpleNamespace(stage=1, to="REF-02", size=300, seed=0)
    for k, v in kw.items():
        setattr(args, k, v)
    with patch("manage.session_factory", return_value=lambda: session):
        manage.cmd_plan_anchors(args)


def test_writes_hidden_anchor_queue_to_reference_account(world):
    run(world)
    rows = world.query(Assignment).filter_by(annotator_id="REF-02").all()
    assert sorted(r.task_id for r in rows) == ["S1::face", "S2::face"]
    assert all(r.is_anchor and r.phase == "pilot" for r in rows)
    # 标注者的队列一条不动
    assert world.query(Assignment).filter_by(annotator_id="P1-EN-01").count() == 3


@pytest.mark.parametrize("target", ["P1-EN-01", "ADMIN-EN-01", "REF"])
def test_only_reference_accounts_take_anchor_queues(world, target):
    with pytest.raises(SystemExit):
        run(world, to=target)


def test_refuses_after_reference_account_started(world):
    with pytest.raises(SystemExit, match="开工"):
        run(world, to="REF-01")
