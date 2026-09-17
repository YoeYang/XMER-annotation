"""清理被顶替的旧版本：只删采样点，保留「重标过几次」这条记录。

Yoe 的口径是重标时只留最新三份。留的是**数据**——采样点占地方；
而重标次数本身是质检信号（标了五遍的人，他的数据要单独看），
所以 `Attempt` 与 `Submission` 的元数据行一条不动。
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

import manage
from app.models import Attempt, SampleChunk, Submission

NOW = datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)


def version(session: Session, annotator, task, dimension, n, minutes):
    """造第 n 版：一条轮次、一条提交、一块采样。"""
    attempt_id = f"{dimension}-{n}"
    session.add(
        Attempt(
            attempt_id=attempt_id, task_id=task, annotator_id=annotator,
            media_id="m", modality="face", mode="annotation",
            dimension=dimension, status="completed", task_snapshot={},
            events=[], sample_rate_hz=10,
            started_at=NOW + timedelta(minutes=minutes),
        )
    )
    session.add(
        Submission(
            submission_id=f"sub-{attempt_id}", task_id=task,
            annotator_id=annotator, attempt_id=attempt_id, dimension=dimension,
            revision=n, submitted_at=NOW + timedelta(minutes=minutes),
        )
    )
    session.add(
        SampleChunk(
            attempt_id=attempt_id, chunk_index=0,
            samples=[{"sample_index": 0, "media_time": 0.0, "value": 0.1}],
        )
    )
    session.commit()


@pytest.fixture
def five_versions(session: Session, annotator, task):
    for n in range(1, 6):
        version(session, annotator.annotator_id, task.task_id, "valence", n, n)
    return task.task_id


class _Args:
    def __init__(self, keep, dry_run=False):
        self.keep = keep
        self.dry_run = dry_run


class _Ctx:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *exc):
        return False


@pytest.fixture
def purge(session: Session, monkeypatch):
    monkeypatch.setattr(manage, "session_factory", lambda: lambda: _Ctx(session))
    return lambda keep=3, dry_run=False: manage.cmd_purge_superseded(
        _Args(keep, dry_run)
    )


def test_only_the_newest_three_keep_their_samples(
    session: Session, five_versions, purge
):
    purge(keep=3)
    left = {row.attempt_id for row in session.query(SampleChunk)}
    assert left == {"valence-3", "valence-4", "valence-5"}


def test_metadata_rows_are_never_deleted(session: Session, five_versions, purge):
    """重标了几次要查得到——占地方的是采样点，不是这几行元数据。"""
    purge(keep=3)
    assert session.query(Attempt).count() == 5
    assert session.query(Submission).count() == 5


def test_each_dimension_keeps_its_own_three(session: Session, annotator, task, purge):
    """效价与唤醒各留各的三份，不能合在一起数。"""
    for n in range(1, 5):
        version(session, annotator.annotator_id, task.task_id, "valence", n, n)
    for n in range(1, 5):
        version(session, annotator.annotator_id, task.task_id, "arousal", n, 10 + n)

    purge(keep=3)
    left = {row.attempt_id for row in session.query(SampleChunk)}
    assert left == {
        "valence-2", "valence-3", "valence-4",
        "arousal-2", "arousal-3", "arousal-4",
    }


def test_nothing_happens_when_there_are_fewer_versions_than_kept(
    session: Session, annotator, task, purge
):
    for n in range(1, 3):
        version(session, annotator.annotator_id, task.task_id, "valence", n, n)
    purge(keep=3)
    assert session.query(SampleChunk).count() == 2


def test_dry_run_reports_without_deleting(session: Session, five_versions, purge):
    purge(keep=3, dry_run=True)
    assert session.query(SampleChunk).count() == 5


def test_keep_must_be_at_least_one(session: Session, five_versions, purge):
    """keep=0 会把最新版也删掉——那不是清理，是丢数据。"""
    with pytest.raises(SystemExit):
        purge(keep=0)
