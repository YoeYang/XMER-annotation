from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def create_db_engine(database_url: str) -> Engine:
    """Postgres 连接池放宽到 20 + 20、排队 10 秒超时（2026-10-03）。

    10.3 线上连接池（默认 5 + 10）被占满整站断开：标注者每交一维就整份重拉
    自己的轮次与提交，单次 2.5 秒且一直占着连接。根治在前端（不再整份重拉），
    这里只是放宽余量；排队等 30 秒不如早点失败，让前端的重试接手。
    """
    if database_url.startswith("postgresql"):
        return create_engine(database_url, future=True, pool_size=20,
                             max_overflow=20, pool_timeout=10, pool_pre_ping=True)
    return create_engine(database_url, future=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_all(engine: Engine) -> None:
    """建表。T1 阶段以模型为唯一真相源；上线前（T5）再引入 Alembic 管理增量迁移。"""
    from . import models  # noqa: F401  确保模型已注册到 Base.metadata

    Base.metadata.create_all(engine)
