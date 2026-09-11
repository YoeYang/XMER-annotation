from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_all, create_db_engine, create_session_factory
from app.models import Annotator, Attempt, Task


@event.listens_for(Engine, "connect")
def _enforce_sqlite_foreign_keys(dbapi_connection, connection_record):
    # SQLite 默认不校验外键，不打开就测不出引用完整性
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_db_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    factory = create_session_factory(engine)
    with factory() as s:
        yield s
    engine.dispose()


@pytest.fixture
def annotator(session: Session) -> Annotator:
    row = Annotator(
        annotator_id="A001", token_hash="hash-a001", phase="pilot", display_name="测试"
    )
    session.add(row)
    session.commit()
    return row


@pytest.fixture
def task(session: Session) -> Task:
    row = Task(
        task_id="EXAMPLE-001",
        media_id="example-visual",
        source_id="meld_dia11_utt9",
        title="真实样本 · 仅视觉",
        modality="visual",
        src="/media/example/visual.mp4",
        duration=6.715,
        speaker_ref_src="/media/example/speaker.jpg",
        speaker_name="Phoebe",
    )
    session.add(row)
    session.commit()
    return row


@pytest.fixture
def attempt(session: Session, annotator: Annotator, task: Task) -> Attempt:
    row = Attempt(
        attempt_id="att-1",
        task_id=task.task_id,
        annotator_id=annotator.annotator_id,
        media_id=task.media_id,
        modality=task.modality,
        mode="annotation",
        status="recording",
        task_snapshot={"task_id": task.task_id},
        events=[],
        sample_rate_hz=10,
        started_at=datetime.now(timezone.utc),
    )
    session.add(row)
    session.commit()
    return row
