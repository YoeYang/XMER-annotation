"""分配只追加、不删改的前置约束（2026-09-29 版）。

释放 / 转移工具本身在后续批次；这里验的是表结构落地后必须立刻成立的三件事：
被释放的分配不再下发、开工后不能整体替换队列、转交链上的账号不能删。
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.assignments import purge_annotator, replace_assignments
from app.auth import hash_token
from app.models import (
    Annotator,
    AnnotatorProfile,
    Assignment,
    AssignmentEvent,
    Attempt,
    Submission,
    Task,
)

NOW = datetime(2026, 9, 30, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def world(session: Session):
    for annotator_id in ("P1-EN-01", "P1-EN-07"):
        session.add(Annotator(annotator_id=annotator_id, phase="main", language="en",
                              token_hash=hash_token(f"token-{annotator_id}")))
    for task_id, source in (("S1::face", "meld_a"), ("S2::face", "meld_b")):
        session.add(Task(task_id=task_id, media_id=task_id, source_id=source,
                         title=task_id, modality="face", src="/x", duration=1.0))
    session.flush()
    for order, task_id in enumerate(("S1::face", "S2::face")):
        session.add(Assignment(annotator_id="P1-EN-01", task_id=task_id,
                               phase="main", order_index=order))
    session.commit()
    return session


def submit(session, annotator_id, task_id):
    session.add(Attempt(attempt_id=f"a-{task_id}", task_id=task_id, annotator_id=annotator_id,
                        media_id=task_id, modality="face", mode="annotation",
                        dimension="valence", status="completed", task_snapshot={},
                        events=[], sample_rate_hz=10, started_at=NOW))
    session.flush()
    session.add(Submission(submission_id=f"s-{task_id}", task_id=task_id,
                           annotator_id=annotator_id, attempt_id=f"a-{task_id}",
                           dimension="valence", revision=1, submitted_at=NOW))
    session.commit()


def queue(client, annotator_id):
    body = client.get("/api/me", headers={"Authorization": f"Bearer token-{annotator_id}"})
    return [t["task_id"] for t in body.json()["tasks"]]


def test_new_assignments_default_to_active(world):
    assert {a.status for a in world.query(Assignment)} == {"active"}


def test_released_assignments_are_not_served(client, world):
    row = world.query(Assignment).filter_by(task_id="S2::face").one()
    row.status, row.released_at = "released", NOW
    world.commit()
    assert queue(client, "P1-EN-01") == ["S1::face"]


def test_replacing_a_started_queue_is_refused(world):
    """开工后整体替换会把做了一半的队列抹掉，只能走释放与转移。"""
    submit(world, "P1-EN-01", "S1::face")
    with pytest.raises(ValueError, match="已经开工"):
        replace_assignments(world, "P1-EN-01", "main", [("meld_b", "face", False)])


def test_replacing_before_any_work_is_allowed(world):
    written, _ = replace_assignments(world, "P1-EN-01", "main", [("meld_b", "face", False)])
    assert written == 1


def test_an_account_in_a_handover_chain_cannot_be_purged(world):
    old = world.query(Assignment).filter_by(task_id="S2::face").one()
    old.status = "released"
    world.add(Assignment(annotator_id="P1-EN-07", task_id="S2::face", phase="main",
                        order_index=0, replaces_assignment_id=old.assignment_id))
    world.commit()
    with pytest.raises(ValueError, match="已转给 P1-EN-07"):
        purge_annotator(world, "P1-EN-01")


def test_purge_also_removes_profile_and_events(world):
    world.add(AnnotatorProfile(annotator_id="P1-EN-01", nationality="FI", age=30))
    world.add(AssignmentEvent(kind="release", annotator_id="P1-EN-01", reason="test"))
    world.commit()
    removed = purge_annotator(world, "P1-EN-01")
    world.commit()
    assert removed["annotator_profiles"] == 1
    assert removed["assignment_events"] == 1
    assert world.get(Annotator, "P1-EN-01") is None
