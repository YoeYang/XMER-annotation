from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import hash_token
from app.config import Settings
from app.db import create_all, create_session_factory
from app.main import create_app
from app.models import Annotator, Assignment, Attempt, Task


@event.listens_for(Engine, "connect")
def _enforce_sqlite_foreign_keys(dbapi_connection, connection_record):
    # SQLite 默认不校验外键，不打开就测不出引用完整性
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@pytest.fixture
def engine() -> Iterator[Engine]:
    # StaticPool 让测试会话与应用共用同一个内存库连接
    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with create_session_factory(engine)() as s:
        yield s


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    app = create_app(
        Settings(database_url="sqlite+pysqlite:///:memory:", admin_token="admin-token"),
        engine=engine,
    )
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------- 数据夹具


@pytest.fixture
def annotator(session: Session) -> Annotator:
    row = Annotator(
        annotator_id="A001",
        token_hash=hash_token("token-a001"),
        phase="pilot",
        display_name="测试",
    )
    session.add(row)
    session.commit()
    return row


@pytest.fixture
def other_annotator(session: Session) -> Annotator:
    row = Annotator(
        annotator_id="A002", token_hash=hash_token("token-a002"), phase="pilot"
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
def second_task(session: Session) -> Task:
    row = Task(
        task_id="EXAMPLE-002",
        media_id="example-audio",
        source_id="meld_dia11_utt9",
        title="真实样本 · 仅音频",
        modality="audio",
        src="/media/example/audio.wav",
        duration=6.715,
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


@pytest.fixture
def second_attempt(session: Session, annotator: Annotator, task: Task) -> Attempt:
    """重标产生的第二个轮次——Update 形成新版本的正当路径。"""
    row = Attempt(
        attempt_id="att-2",
        task_id=task.task_id,
        annotator_id=annotator.annotator_id,
        media_id=task.media_id,
        modality=task.modality,
        mode="annotation",
        status="completed",
        task_snapshot={"task_id": task.task_id},
        events=[],
        sample_rate_hz=10,
        started_at=datetime.now(timezone.utc),
    )
    session.add(row)
    session.commit()
    return row


# --------------------------------------------------------------- 请求头夹具


@pytest.fixture
def auth(annotator: Annotator) -> dict[str, str]:
    return {"Authorization": "Bearer token-a001"}


@pytest.fixture
def other_auth(other_annotator: Annotator) -> dict[str, str]:
    return {"Authorization": "Bearer token-a002"}


@pytest.fixture
def assigned(
    session: Session, annotator: Annotator, task: Task, auth: dict[str, str]
) -> dict[str, str]:
    """A001 已分配到 EXAMPLE-001，返回可直接使用的请求头。"""
    session.add(
        Assignment(
            annotator_id=annotator.annotator_id,
            task_id=task.task_id,
            phase="pilot",
            order_index=0,
        )
    )
    session.commit()
    return auth


@pytest.fixture
def other_assigned(
    session: Session,
    other_annotator: Annotator,
    task: Task,
    other_auth: dict[str, str],
) -> dict[str, str]:
    session.add(
        Assignment(
            annotator_id=other_annotator.annotator_id,
            task_id=task.task_id,
            phase="pilot",
            order_index=0,
        )
    )
    session.commit()
    return other_auth
