from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def create_db_engine(database_url: str) -> Engine:
    return create_engine(database_url, future=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_all(engine: Engine) -> None:
    """建表。T1 阶段以模型为唯一真相源；上线前（T5）再引入 Alembic 管理增量迁移。"""
    from . import models  # noqa: F401  确保模型已注册到 Base.metadata

    Base.metadata.create_all(engine)
