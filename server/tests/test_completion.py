"""完成判定：两个维度都交了，这个子任务才算标完。

V3 一个子任务要标效价与唤醒两轮。按提交条数或按 task_id 去重来数「完成多少」
都会把只标了一半的算成标完——进度表看着漂亮，实际交上来的数据缺一半维度，
而这件事要等到分析阶段才暴露。
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.completion import completed_tasks, latest_submissions, superseded_ids
from app.models import Attempt, Submission

NOW = datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)


def record(session: Session, annotator, task, dimension, *, attempt, revision,
           previous=None, minutes=0):
    session.add(
        Attempt(
            attempt_id=attempt, task_id=task, annotator_id=annotator,
            media_id="m", modality="face", mode="annotation",
            dimension=dimension, status="completed",
            task_snapshot={}, events=[], sample_rate_hz=10,
            started_at=NOW + timedelta(minutes=minutes),
        )
    )
    row = Submission(
        submission_id=f"sub-{attempt}", task_id=task, annotator_id=annotator,
        attempt_id=attempt, dimension=dimension, revision=revision,
        previous_submission_id=previous,
        submitted_at=NOW + timedelta(minutes=minutes),
    )
    session.add(row)
    session.commit()
    return row


# --------------------------------------------------------------- 完成判定


def test_one_dimension_alone_is_not_complete(session: Session, annotator, task):
    record(session, annotator.annotator_id, task.task_id, "valence",
           attempt="a1", revision=1)
    assert completed_tasks(session, annotator.annotator_id) == set()


def test_both_dimensions_make_it_complete(session: Session, annotator, task):
    record(session, annotator.annotator_id, task.task_id, "valence",
           attempt="a1", revision=1)
    record(session, annotator.annotator_id, task.task_id, "arousal",
           attempt="a2", revision=1, minutes=5)
    assert completed_tasks(session, annotator.annotator_id) == {task.task_id}


def test_redoing_one_dimension_twice_is_still_not_both(
    session: Session, annotator, task
):
    """同一维度标三遍也凑不齐两个维度——数条数就会在这里出错。"""
    for n in range(1, 4):
        record(session, annotator.annotator_id, task.task_id, "valence",
               attempt=f"a{n}", revision=n,
               previous=f"sub-a{n-1}" if n > 1 else None, minutes=n)
    assert completed_tasks(session, annotator.annotator_id) == set()


def test_completion_is_per_annotator(session: Session, annotator,
                                     other_annotator, task):
    """两个人各标一个维度，凑不成一份完整标注——各自都不算完成。"""
    record(session, annotator.annotator_id, task.task_id, "valence",
           attempt="a1", revision=1)
    record(session, other_annotator.annotator_id, task.task_id, "arousal",
           attempt="a2", revision=1, minutes=5)
    assert completed_tasks(session, annotator.annotator_id) == set()
    assert completed_tasks(session, other_annotator.annotator_id) == set()


# --------------------------------------------------------------- 取最新


def test_latest_keeps_only_the_newest_of_each_dimension(
    session: Session, annotator, task
):
    record(session, annotator.annotator_id, task.task_id, "valence",
           attempt="a1", revision=1)
    record(session, annotator.annotator_id, task.task_id, "valence",
           attempt="a2", revision=2, previous="sub-a1", minutes=5)
    record(session, annotator.annotator_id, task.task_id, "arousal",
           attempt="a3", revision=1, minutes=10)

    latest = latest_submissions(session, annotator.annotator_id)
    assert {(s.dimension, s.revision) for s in latest} == {
        ("valence", 2), ("arousal", 1)
    }


def test_superseded_marks_every_version_but_the_newest(
    session: Session, annotator, task
):
    record(session, annotator.annotator_id, task.task_id, "valence",
           attempt="a1", revision=1)
    record(session, annotator.annotator_id, task.task_id, "valence",
           attempt="a2", revision=2, previous="sub-a1", minutes=5)
    record(session, annotator.annotator_id, task.task_id, "arousal",
           attempt="a3", revision=1, minutes=10)

    assert superseded_ids(session) == {"sub-a1"}


def test_nothing_is_superseded_when_each_dimension_has_one_version(
    session: Session, annotator, task
):
    record(session, annotator.annotator_id, task.task_id, "valence",
           attempt="a1", revision=1)
    record(session, annotator.annotator_id, task.task_id, "arousal",
           attempt="a2", revision=1, minutes=5)
    assert superseded_ids(session) == set()


# --------------------------------------------------------------- 导出


def test_export_marks_superseded_versions_but_keeps_them(
    client, session: Session, annotator, task, assigned
):
    """旧版留在导出里——重标过几次是质检信号——但要标出来供分析跳过。"""
    from app.export import build_export

    record(session, annotator.annotator_id, task.task_id, "valence",
           attempt="a1", revision=1)
    record(session, annotator.annotator_id, task.task_id, "valence",
           attempt="a2", revision=2, previous="sub-a1", minutes=5)
    record(session, annotator.annotator_id, task.task_id, "arousal",
           attempt="a3", revision=1, minutes=10)

    data = build_export(session, annotator)
    rows = {s["submission_id"]: s for s in data["submissions"]}

    assert len(rows) == 3, "旧版不删"
    assert rows["sub-a1"]["superseded"] is True
    assert rows["sub-a2"]["superseded"] is False
    assert rows["sub-a3"]["superseded"] is False
    assert rows["sub-a3"]["dimension"] == "arousal"


def test_export_attempts_carry_the_dimension(
    client, session: Session, annotator, task, assigned
):
    """轮次也要带维度，否则导出里分不清这条曲线标的是哪一维。"""
    from app.export import build_export

    record(session, annotator.annotator_id, task.task_id, "arousal",
           attempt="a1", revision=1)
    data = build_export(session, annotator)
    assert data["attempts"][0]["dimension"] == "arousal"
