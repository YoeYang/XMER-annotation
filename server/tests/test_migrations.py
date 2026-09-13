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
