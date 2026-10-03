"""只读大接口查完即归还连接（2026-10-03 连接池占满事故）。"""
from datetime import datetime, timezone

from app import api
from app.models import Annotator, Attempt, Submission, Task

NOW = datetime(2026, 10, 3, tzinfo=timezone.utc)


def seed(session):
    a = Annotator(annotator_id="P1-EN-01", token_hash="h", phase="main", language="en")
    session.add(a)
    session.add(Task(task_id="T::face", media_id="T", source_id="T", title="T",
                     modality="face", src="/x", duration=1.0))
    session.flush()
    session.add(Attempt(attempt_id="a1", task_id="T::face", annotator_id="P1-EN-01",
                        media_id="T", modality="face", mode="annotation", dimension="valence",
                        status="completed", task_snapshot={"k": 1},
                        events=[{"index": 0, "type": "start"}], sample_rate_hz=10,
                        started_at=NOW))
    session.flush()
    session.add(Submission(submission_id="s1", task_id="T::face", annotator_id="P1-EN-01",
                           attempt_id="a1", dimension="valence", revision=1, submitted_at=NOW))
    session.commit()
    return a


def test_list_attempts_releases_connection_and_keeps_every_field(session):
    annotator = seed(session)
    out = api.list_attempts(annotator=annotator, session=session)
    assert not session.in_transaction(), "整理返回内容之前连接必须已归还"
    assert out[0].events == [{"index": 0, "type": "start"}]
    assert out[0].task_snapshot == {"k": 1}


def test_list_submissions_releases_connection(session):
    annotator = seed(session)
    out = api.list_submissions(annotator=annotator, session=session)
    assert not session.in_transaction()
    assert out[0].submission_id == "s1"


def test_me_releases_connection(session):
    annotator = seed(session)
    out = api.read_me(view=None, annotator=annotator, session=session)
    assert not session.in_transaction()
    assert out.annotator_id == "P1-EN-01"
