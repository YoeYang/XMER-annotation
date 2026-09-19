import os
from dataclasses import dataclass

PHASES = ("pilot", "training", "main")

MODALITIES = ("face", "body", "audio", "text", "audiovisual")
"""V3 把原来的 `visual` 拆成 `face`（只看脸）与 `body`（脸被遮住、只看身体）。

顺序即标注顺序：视觉两路在前、音频文本居中、完整视频压轴，
与前端 `taskFlow.ts` 的 MODALITY_ORDER 一致，两边改动必须同步。
"""

LANGUAGES = ("en", "zh")
"""标注者的语言标签，决定两件事：训练页给哪一版，正式分配里能拿哪些子任务。

**`zh` 的含义是「中英都能读」，不是「只读中文」**——中文标注者同样要标英文素材。
chsims 的 `text` 与 `audiovisual` 只能分给 `zh`：那两个模态要读懂中文，
其余模态与语言无关（面部与肢体本就无关，音频按设计只听韵律）。
"""

DIMENSIONS = ("valence", "arousal")
"""V3 一次只标一个维度。一个子任务要效价轮与唤醒轮都提交才算完成。"""


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
