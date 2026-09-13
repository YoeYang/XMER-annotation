"""Alembic 环境。

数据库地址取自 `XMER_DATABASE_URL`，和应用同源——迁移跑到另一个库上
是这类工具最容易造成的事故。
"""

import sqlalchemy as sa
from alembic import context

from app.config import load_settings
from app.db import Base, create_db_engine
from app import models  # noqa: F401  让 Base.metadata 拿到全部表

target_metadata = Base.metadata


def render_item(type_, obj, autogen_context):
    """把 JSON 列渲染成模型里的 `JsonCol`。

    默认渲染会输出 `postgresql.JSONB(astext_type=Text())` —— 少了 `sa.` 前缀，
    生成的脚本一跑就 NameError。每次 autogenerate 碰到 JSON 列都会再犯，
    所以在这里统一指向模型中的那个具名类型。
    """
    if type_ == "type" and isinstance(obj, sa.JSON):
        autogen_context.imports.add("from app.models import JsonCol")
        return "JsonCol"
    return False


def run_migrations_online() -> None:
    engine = create_db_engine(load_settings().database_url)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_item=render_item,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=load_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
