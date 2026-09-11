import os
from dataclasses import dataclass

PHASES = ("pilot", "training", "main")
MODALITIES = ("visual", "audio", "text", "audiovisual")


@dataclass(frozen=True)
class Settings:
    database_url: str
    admin_token: str


def load_settings() -> Settings:
    """从环境变量读取配置。

    `XMER_DATABASE_URL` 没有缺省值，是刻意的：这个服务会写标注数据、建账号，
    一旦缺省回落到本地 SQLite，就会在"看起来一切正常"的情况下把数据写错地方。
    宁可起不来。
    """
    database_url = os.environ.get("XMER_DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "缺少 XMER_DATABASE_URL。请显式指定数据库，例如本地开发用 "
            "sqlite+pysqlite:///./dev.db，生产用 postgresql+psycopg://…"
        )
    return Settings(
        database_url=database_url,
        admin_token=os.environ.get("XMER_ADMIN_TOKEN", ""),
    )
