import os
from dataclasses import dataclass

PHASES = ("pilot", "training", "main")
MODALITIES = ("visual", "audio", "text", "audiovisual")


@dataclass(frozen=True)
class Settings:
    database_url: str
    admin_token: str


def load_settings() -> Settings:
    # 生产环境由 docker-compose 注入；缺省值仅供本地开发
    return Settings(
        database_url=os.environ.get(
            "XMER_DATABASE_URL", "sqlite+pysqlite:///./xmer_annotation.db"
        ),
        admin_token=os.environ.get("XMER_ADMIN_TOKEN", ""),
    )
