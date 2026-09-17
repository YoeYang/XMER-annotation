"""迁移与模型必须始终一致。

改了 `models.py` 却忘记生成迁移，本地 `create_all` 照样能跑（新库直接按新模型建表），
线上却会因为老表没有新列而崩——这个测试就是拦这种漏。
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app.db import Base

SERVER = Path(__file__).parent.parent


@pytest.fixture
def migrated(tmp_path, monkeypatch):
    """在空库上跑完全部迁移，返回引擎。"""
    url = f"sqlite+pysqlite:///{tmp_path/'m.db'}"
    monkeypatch.setenv("XMER_DATABASE_URL", url)
    config = Config(str(SERVER / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER / "migrations"))
    cwd = os.getcwd()
    os.chdir(SERVER)
    try:
        command.upgrade(config, "head")
    finally:
        os.chdir(cwd)
    return create_engine(url)


def test_migrations_create_every_table(migrated):
    from sqlalchemy import inspect

    tables = set(inspect(migrated).get_table_names())
    assert set(Base.metadata.tables) <= tables


def test_no_drift_between_models_and_migrations(migrated):
    """迁移跑完后的库，与模型定义不应再有差异。"""
    with migrated.connect() as connection:
        context = MigrationContext.configure(connection)
        diff = compare_metadata(context, Base.metadata)
    assert diff == [], f"模型与迁移不一致，请生成新迁移：{diff}"


# ------------------------------------------------- 提交记录带上维度（7ae2d41c9f08）


@pytest.fixture
def at_paradigm_v3(tmp_path, monkeypatch):
    """升到 `3c1f5a90b7d2` 为止——此时轮次已有维度，提交还没有。"""
    url = f"sqlite+pysqlite:///{tmp_path/'back.db'}"
    monkeypatch.setenv("XMER_DATABASE_URL", url)
    config = Config(str(SERVER / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER / "migrations"))
    cwd = os.getcwd()
    os.chdir(SERVER)
    try:
        command.upgrade(config, "3c1f5a90b7d2")
    finally:
        os.chdir(cwd)
    return create_engine(url), config


def _seed_two_dimensions(engine):
    """造一条被旧约束搅在一起的链：效价 v1、唤醒 v2、效价 v3。

    旧编号是在 `(标注者, 子任务)` 这个错误分组下算出来的——唤醒凭空成了
    效价的修订版。迁移要把它拆成两条各自从 1 开始的链。
    """
    from sqlalchemy import text

    rows = [
        ("s1", "att-v1", "valence", 1, None, "2026-09-17 10:00:00"),
        ("s2", "att-a1", "arousal", 2, "s1", "2026-09-17 10:05:00"),
        ("s3", "att-v2", "valence", 3, "s2", "2026-09-17 10:10:00"),
    ]
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO annotators (annotator_id, display_name, token_hash, "
            "phase, active, created_at) VALUES ('A1', 'A', 'h', 'main', 1, '2026-09-17')"
        ))
        conn.execute(text(
            "INSERT INTO tasks (task_id, media_id, source_id, title, modality, "
            "src, duration, target, demo, timeline_origin) VALUES "
            "('T1', 'm', 'src', 't', 'face', 's', 1.0, '', 0, 0.0)"
        ))
        for sid, aid, dim, rev, prev, when in rows:
            conn.execute(text(
                "INSERT INTO attempts (attempt_id, task_id, annotator_id, media_id, "
                "modality, mode, dimension, familiarization_plays, status, "
                "task_snapshot, events, sample_rate_hz, started_at, sample_count, "
                "last_media_time, server_received_at) VALUES "
                f"('{aid}', 'T1', 'A1', 'm', 'face', 'annotation', '{dim}', 0, "
                f"'completed', '{{}}', '[]', 10, '{when}', 0, 0.0, '{when}')"
            ))
            conn.execute(text(
                "INSERT INTO submissions (submission_id, task_id, annotator_id, "
                "attempt_id, revision, previous_submission_id, submitted_at) VALUES "
                f"('{sid}', 'T1', 'A1', '{aid}', {rev}, "
                f"{'NULL' if prev is None else repr(prev)}, '{when}')"
            ))


def _upgrade_to_head(config):
    cwd = os.getcwd()
    os.chdir(SERVER)
    try:
        command.upgrade(config, "head")
    finally:
        os.chdir(cwd)


def test_dimension_is_backfilled_from_the_attempt(at_paradigm_v3):
    engine, config = at_paradigm_v3
    _seed_two_dimensions(engine)
    _upgrade_to_head(config)

    from sqlalchemy import text

    with engine.connect() as conn:
        got = dict(conn.execute(text(
            "SELECT submission_id, dimension FROM submissions"
        )).all())
    assert got == {"s1": "valence", "s2": "arousal", "s3": "valence"}


def test_revisions_are_renumbered_per_dimension(at_paradigm_v3):
    """两条链各自从 1 开始，previous 只在同维度内相连。"""
    engine, config = at_paradigm_v3
    _seed_two_dimensions(engine)
    _upgrade_to_head(config)

    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT submission_id, revision, previous_submission_id "
            "FROM submissions ORDER BY submission_id"
        )).all()
    got = {r[0]: (r[1], r[2]) for r in rows}
    assert got["s1"] == (1, None)
    assert got["s2"] == (1, None), "唤醒是自己那条链的第一版，不接在效价后面"
    assert got["s3"] == (2, "s1"), "效价的第二版要指回效价的第一版"
