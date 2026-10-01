"""阶段进度监控（2026-10-01 版）。"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.auth import hash_token
from app.models import Annotator, Assignment, Attempt, Submission, Task
from app.monitor import DEADLINES, build_monitor

ADMIN = {"Authorization": "Bearer admin-token"}
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def add_annotator(session, aid, language="en", trained_at=None):
    session.add(Annotator(annotator_id=aid, token_hash=hash_token(aid), phase="main",
                          language=language, trained_at=trained_at))


def add_tasks(session, aid, phase, n, prefix):
    ids = []
    for i in range(n):
        tid = f"{prefix}-{i}"
        if session.get(Task, tid) is None:
            session.add(Task(task_id=tid, media_id=tid, source_id=tid, title=tid,
                             modality="face", src="/x", duration=4.0))
        ids.append(tid)
    session.flush()
    for i, tid in enumerate(ids):
        session.add(Assignment(annotator_id=aid, task_id=tid, phase=phase, order_index=i))
    session.flush()
    return ids


def attempt(session, aid, tid, dimension, at):
    att_id = f"{aid}-{tid}-{dimension}-{at.timestamp()}"
    session.add(Attempt(attempt_id=att_id, task_id=tid, annotator_id=aid, media_id=tid,
                        modality="face", mode="annotation", dimension=dimension,
                        status="completed", task_snapshot={}, events=[], sample_rate_hz=10,
                        started_at=at, server_received_at=at))
    session.flush()
    return att_id


def submit(session, aid, tid, dimension, at, revision=1):
    att_id = attempt(session, aid, tid, dimension, at)
    session.add(Submission(submission_id=att_id, task_id=tid, annotator_id=aid,
                           attempt_id=att_id, dimension=dimension, revision=revision,
                           submitted_at=at))
    session.flush()


def finish(session, aid, tid, at):
    submit(session, aid, tid, "valence", at - timedelta(seconds=10))
    submit(session, aid, tid, "arousal", at)


def row(body, aid):
    return next(r for r in body["annotators"] if r["annotator_id"] == aid)


@pytest.fixture
def world(session: Session):
    add_annotator(session, "P1-ZH-01", "zh", trained_at=NOW - timedelta(days=1))
    add_annotator(session, "P1-EN-01")
    add_annotator(session, "ADMIN-ZH-01", "zh")
    add_annotator(session, "P2-EN-01")
    session.flush()
    add_tasks(session, "P1-ZH-01", "training", 2, "TR")
    main = add_tasks(session, "P1-ZH-01", "main", 100, "M")
    add_tasks(session, "P1-EN-01", "training", 2, "TR")
    add_tasks(session, "P1-EN-01", "main", 100, "M")
    add_tasks(session, "ADMIN-ZH-01", "main", 100, "M")
    add_tasks(session, "P2-EN-01", "main", 100, "M")
    for i in range(2):
        finish(session, "P1-ZH-01", f"TR-{i}", NOW - timedelta(days=1, minutes=10 - i))
    session.commit()
    return session, main


def test_only_this_stages_annotators_are_listed(world):
    session, _ = world
    body = build_monitor(session, 1, NOW)
    assert [r["annotator_id"] for r in body["annotators"]] == ["P1-EN-01", "P1-ZH-01"]


def test_states_follow_the_annotators_progress(world):
    session, main = world
    attempt(session, "P1-EN-01", "TR-0", "valence", NOW)
    session.commit()
    body = build_monitor(session, 1, NOW)
    assert row(body, "P1-EN-01")["state"] == "training"
    assert row(body, "P1-ZH-01")["state"] == "trained"
    assert row(body, "P1-ZH-01")["training"] == {
        "done": 2, "total": 2, "trained_at": row(body, "P1-ZH-01")["training"]["trained_at"]}

    attempt(session, "P1-ZH-01", main[0], "valence", NOW)
    session.commit()
    assert row(build_monitor(session, 1, NOW), "P1-ZH-01")["state"] == "annotating"


def test_not_started_has_no_activity(world):
    session, _ = world
    r = row(build_monitor(session, 1, NOW), "P1-EN-01")
    assert r["state"] == "not_started" and r["last_activity"] is None and not r["idle"]


def test_half_done_subtask_is_not_counted(world):
    session, main = world
    submit(session, "P1-ZH-01", main[0], "valence", NOW)
    session.commit()
    assert row(build_monitor(session, 1, NOW), "P1-ZH-01")["main"]["done"] == 0


def test_redo_does_not_count_twice(world):
    session, main = world
    finish(session, "P1-ZH-01", main[0], NOW - timedelta(minutes=5))
    submit(session, "P1-ZH-01", main[0], "valence", NOW, revision=2)
    session.commit()
    assert row(build_monitor(session, 1, NOW), "P1-ZH-01")["main"]["done"] == 1


def test_released_assignments_are_not_counted(world):
    session, main = world
    session.query(Assignment).filter_by(annotator_id="P1-ZH-01", task_id=main[0]).update(
        {"status": "released"})
    session.commit()
    assert row(build_monitor(session, 1, NOW), "P1-ZH-01")["main"]["total"] == 99


def test_pace_ignores_breaks_and_predicts(world):
    session, main = world
    # 昨天 30 条每 15 秒一条，中间歇了 8 小时，今天又 30 条每 15 秒一条
    start = NOW - timedelta(hours=20)
    for i in range(30):
        finish(session, "P1-ZH-01", main[i], start + timedelta(seconds=15 * i))
    for i in range(30, 60):
        finish(session, "P1-ZH-01", main[i], NOW - timedelta(hours=1) + timedelta(seconds=15 * i))
    session.commit()
    r = row(build_monitor(session, 1, NOW), "P1-ZH-01")
    assert r["main"]["done"] == 60 and r["main"]["percent"] == 60
    assert r["pace"]["sec_per_task"] == 15.0, "8 小时的空档不能算进每条用时"
    assert r["pace"]["hours_left"] == round(40 * 15 / 3600, 1)
    # 开标才 20 小时：60 条按 20 小时折算成每天 72 条
    assert r["pace"]["forecast"] == {"per_day": 72, "on_track": True}
    assert r["pace"]["needed_per_day"] >= 1


def test_too_little_data_gives_no_pace(world):
    session, main = world
    for i in range(5):
        finish(session, "P1-ZH-01", main[i], NOW - timedelta(minutes=5 - i))
    session.commit()
    pace = row(build_monitor(session, 1, NOW), "P1-ZH-01")["pace"]
    assert pace["sec_per_task"] is None and pace["hours_left"] is None
    assert pace["sec_median"] is None and pace["sec_min"] is None and pace["sec_max"] is None
    assert pace["forecast"] is None, "开标不到 6 小时不预测"


def test_falling_behind_is_flagged(world):
    session, main = world
    for i in range(3):
        finish(session, "P1-ZH-01", main[i], NOW - timedelta(hours=10, minutes=-i))
    session.commit()
    near_deadline = DEADLINES[1] - timedelta(hours=12)
    forecast = row(build_monitor(session, 1, near_deadline), "P1-ZH-01")["pace"]["forecast"]
    assert forecast["on_track"] is False


def test_idle_after_a_day_without_activity(world):
    session, main = world
    finish(session, "P1-ZH-01", main[0], NOW - timedelta(hours=30))
    session.commit()
    assert row(build_monitor(session, 1, NOW), "P1-ZH-01")["idle"] is True
    assert row(build_monitor(session, 1, NOW - timedelta(hours=20)), "P1-ZH-01")["idle"] is False


def test_finished_annotator_is_done_and_not_idle(world):
    session, main = world
    for i, tid in enumerate(main):
        finish(session, "P1-ZH-01", tid, NOW - timedelta(days=2, seconds=-15 * i))
    session.commit()
    r = row(build_monitor(session, 1, NOW), "P1-ZH-01")
    assert r["state"] == "done" and r["idle"] is False and r["pace"]["forecast"] is None


def test_today_uses_local_midnight(world):
    session, main = world
    # 本地 UTC+3：10.3 00:30 本地 = 10.2 21:30 UTC，算「今天」；21:00 UTC 之前算昨天
    finish(session, "P1-ZH-01", main[0], datetime(2026, 10, 2, 21, 30, tzinfo=timezone.utc))
    finish(session, "P1-ZH-01", main[1], datetime(2026, 10, 2, 20, 30, tzinfo=timezone.utc))
    session.commit()
    assert row(build_monitor(session, 1, NOW), "P1-ZH-01")["main"]["today"] == 1


def test_endpoint_requires_admin(client, world):
    assert client.get("/api/admin/monitor").status_code == 401
    body = client.get("/api/admin/monitor?stage=1", headers=ADMIN).json()
    assert body["stage"] == 1 and body["totals"]["annotators"] == 2


def test_task_seconds_spread_excludes_breaks(world):
    """单条用时：上一条提交到这一条提交；超过 10 分钟的间隔是休息，不进最长。"""
    session, main = world
    gaps = [20, 30, 40] * 8 + [9 * 60]           # 25 个有效间隔，最长 9 分钟
    at = NOW - timedelta(hours=3)
    finish(session, "P1-ZH-01", main[0], at)
    for i, gap in enumerate(gaps, start=1):
        at += timedelta(seconds=gap)
        finish(session, "P1-ZH-01", main[i], at)
    at += timedelta(hours=1)                      # 午休
    finish(session, "P1-ZH-01", main[len(gaps) + 1], at)
    session.commit()
    pace = row(build_monitor(session, 1, NOW), "P1-ZH-01")["pace"]
    assert pace["sec_min"] == 20.0
    assert pace["sec_max"] == 540.0, "9 分钟算一条；1 小时午休不算"
    assert pace["sec_median"] == 30.0


def test_training_subtask_in_main_queue_does_not_mean_annotating(world):
    """10.1 误报：P1-EN-06 训练里交的子任务恰好也在正式队列，监控报「开始正式标注」。
    没写 trained_at 的正式账号还在训练，不能算正式标注中。"""
    session, main = world
    session.add(Assignment(annotator_id="P1-EN-01", task_id=main[0], phase="training",
                           order_index=99))
    session.flush()
    finish(session, "P1-EN-01", main[0], NOW)
    session.commit()
    assert row(build_monitor(session, 1, NOW), "P1-EN-01")["state"] == "training"
