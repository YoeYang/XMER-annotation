"""有人退出换人：未完成分配整体转给接手者（2026-10-04）。"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

import manage
from app.assignments import transfer_unfinished
from app.auth import hash_token
from app.models import Annotator, Assignment, AssignmentEvent, Attempt, Submission, Task
from app.monitor import build_monitor

NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)


def submit(session, aid, tid, dim):
    att = f"{aid}-{tid}-{dim}"
    session.add(Attempt(attempt_id=att, task_id=tid, annotator_id=aid, media_id=tid,
                        modality="face", mode="annotation", dimension=dim, status="completed",
                        task_snapshot={}, events=[], sample_rate_hz=10, started_at=NOW))
    session.flush()
    session.add(Submission(submission_id=att, task_id=tid, annotator_id=aid, attempt_id=att,
                           dimension=dim, revision=1, submitted_at=NOW))
    session.flush()


@pytest.fixture
def world(session: Session):
    for aid, lang in [("P1-EN-03", "en"), ("P1-EN-08", "en"), ("P1-ZH-01", "zh")]:
        session.add(Annotator(annotator_id=aid, token_hash=hash_token(aid), phase="main",
                              language=lang))
    specs = [("meld_a", "face"), ("meld_b", "body"), ("meld_c", "audio"),
             ("meld_d", "text"), ("meld_e", "face")]
    for sid, mod in specs:
        session.add(Task(task_id=f"{sid}::{mod}", media_id=sid, source_id=sid, title=sid,
                         modality=mod, src="/x", duration=1.0))
    session.add(Task(task_id="chsims_x::text", media_id="x", source_id="chsims_x", title="x",
                     modality="text", src="/x", duration=1.0))
    session.add(Task(task_id="TR::face", media_id="TR", source_id="meld_tr", title="TR",
                     modality="face", src="/x", duration=1.0))
    session.flush()
    for i, (sid, mod) in enumerate(specs):
        session.add(Assignment(annotator_id="P1-EN-03", task_id=f"{sid}::{mod}", phase="main",
                               order_index=10 + i, is_anchor=(i == 4)))
    session.add(Assignment(annotator_id="P1-EN-03", task_id="TR::face", phase="training",
                           order_index=0))
    session.add(Assignment(annotator_id="P1-EN-08", task_id="TR::face", phase="training",
                           order_index=0))
    session.flush()
    submit(session, "P1-EN-03", "meld_a::face", "valence")       # 标完
    submit(session, "P1-EN-03", "meld_a::face", "arousal")
    submit(session, "P1-EN-03", "meld_b::body", "valence")       # 只标了一维
    session.commit()
    return session


def active(session, aid, phase="main"):
    return session.query(Assignment).filter_by(annotator_id=aid, phase=phase,
                                               status="active").order_by(Assignment.order_index).all()


def test_moves_only_unfinished_in_order_and_keeps_the_chain(world):
    event, moved = transfer_unfinished(world, "P1-EN-03", "P1-EN-08", "退出")
    world.commit()
    assert moved == 4
    new = active(world, "P1-EN-08")
    assert [r.task_id for r in new] == ["meld_b::body", "meld_c::audio", "meld_d::text", "meld_e::face"]
    assert [r.order_index for r in new] == [0, 1, 2, 3]
    assert new[-1].is_anchor is True
    old = {r.assignment_id: r for r in world.query(Assignment).filter_by(annotator_id="P1-EN-03", phase="main")}
    for r in new:
        src = old[r.replaces_assignment_id]
        assert src.task_id == r.task_id and src.status == "released"
        assert src.release_event_id == event.event_id and src.released_at is not None
    assert [r.task_id for r in active(world, "P1-EN-03")] == ["meld_a::face"]
    assert event.kind == "transfer" and event.detail == {
        "to": "P1-EN-08", "phase": "main", "count": 4, "kept_done": 1}


def test_training_is_untouched(world):
    transfer_unfinished(world, "P1-EN-03", "P1-EN-08", "退出")
    world.commit()
    assert len(active(world, "P1-EN-03", "training")) == 1


def test_half_done_submission_stays_in_the_database(world):
    transfer_unfinished(world, "P1-EN-03", "P1-EN-08", "退出")
    world.commit()
    assert world.query(Submission).filter_by(annotator_id="P1-EN-03").count() == 3


def test_refuses_when_target_already_holds_a_subtask(world):
    world.add(Assignment(annotator_id="P1-EN-08", task_id="meld_c::audio", phase="main",
                         order_index=0))
    world.commit()
    with pytest.raises(ValueError, match="重复"):
        transfer_unfinished(world, "P1-EN-03", "P1-EN-08", "退出")
    world.rollback()
    assert world.query(AssignmentEvent).count() == 0
    assert len(active(world, "P1-EN-03")) == 5


def test_refuses_zh_only_subtasks_for_english_target(world):
    world.add(Assignment(annotator_id="P1-ZH-01", task_id="chsims_x::text", phase="main",
                         order_index=0))
    world.add(Annotator(annotator_id="P1-EN-09", token_hash="h9", phase="main", language="en"))
    world.commit()
    with pytest.raises(ValueError, match="中文专属"):
        transfer_unfinished(world, "P1-ZH-01", "P1-EN-09", "退出")


def test_appends_after_targets_existing_queue(world):
    world.add(Task(task_id="meld_z::face", media_id="z", source_id="meld_z", title="z",
                   modality="face", src="/x", duration=1.0))
    world.flush()
    world.add(Assignment(annotator_id="P1-EN-08", task_id="meld_z::face", phase="main",
                         order_index=7))
    world.commit()
    transfer_unfinished(world, "P1-EN-03", "P1-EN-08", "退出")
    world.commit()
    assert [r.order_index for r in active(world, "P1-EN-08")] == [7, 8, 9, 10, 11]


@pytest.mark.parametrize("src,dst", [("P1-EN-03", "P1-EN-03"), ("P1-EN-03", "NOPE"),
                                     ("NOPE", "P1-EN-08")])
def test_refuses_bad_accounts(world, src, dst):
    with pytest.raises(ValueError):
        transfer_unfinished(world, src, dst, "退出")


def test_nothing_left_to_move(world):
    transfer_unfinished(world, "P1-EN-03", "P1-EN-08", "退出")
    world.commit()
    with pytest.raises(ValueError, match="没有未完成"):
        transfer_unfinished(world, "P1-EN-03", "P1-EN-08", "又一次")


def test_command_deactivates_source_and_old_link_stops_working(world, client):
    args = SimpleNamespace(source="P1-EN-03", to="P1-EN-08", reason="退出", phase="main",
                           deactivate=True)
    with patch("manage.session_factory", return_value=lambda: world):
        manage.cmd_transfer(args)
    world.expire_all()
    assert world.get(Annotator, "P1-EN-03").active is False


def test_monitor_after_transfer(world):
    transfer_unfinished(world, "P1-EN-03", "P1-EN-08", "退出")
    world.commit()
    body = build_monitor(world, 1, NOW)
    rows = {r["annotator_id"]: r for r in body["annotators"]}
    assert rows["P1-EN-03"]["main"]["total"] == 1 and rows["P1-EN-03"]["main"]["done"] == 1
    assert rows["P1-EN-08"]["main"]["total"] == 4 and rows["P1-EN-08"]["main"]["done"] == 0
    assert rows["P1-EN-08"]["active"] is True


def test_monitor_marks_deactivated_account(world):
    world.get(Annotator, "P1-EN-03").active = False
    world.commit()
    rows = {r["annotator_id"]: r for r in build_monitor(world, 1, NOW)["annotators"]}
    assert rows["P1-EN-03"]["active"] is False


def test_kept_done_counts_only_this_phase(world):
    """10.4 线上：EN-03 正式只完成 6 条，事件却记「保留已完成 17 条」——把训练也算进去了。"""
    submit(world, "P1-EN-03", "TR::face", "valence")
    submit(world, "P1-EN-03", "TR::face", "arousal")
    world.commit()
    event, _ = transfer_unfinished(world, "P1-EN-03", "P1-EN-08", "退出")
    assert event.detail["kept_done"] == 1
