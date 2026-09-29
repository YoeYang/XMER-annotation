import os
import re
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

ZH_ONLY_DATASETS = ("chsims",)
ZH_ONLY_MODALITIES = ("text", "audiovisual")
"""这两者的交集只能分给 `zh` 标注者。数据集由样本名前缀判定（`chsims_…`）。"""

ZH_OPEN_QUOTA = 300
"""中文标注者的英文定额：每人在 ZH_ONLY_MODALITIES 的每个模态上，另拿这么多条
**非** chsims 的子任务（Yoe 2026-09-29 定，阶段一）。用来量中文组与英文组在
同类材料上的系统差异；不设的话他们一条英文 text/full 都拿不到。"""


def dataset_of(sample_id: str) -> str:
    return sample_id.split("_", 1)[0]


STAGE_ACCOUNT = re.compile(r"^P(?P<stage>\d+)-(?P<lang>ZH|EN)-(?P<number>\d{2,})$")
"""正式标注者编号 `P<阶段>-<语言>-<序号>`，如 `P1-ZH-01`（2026-09-29 定）。

编号里的语言与 `annotators.language` 必须一致；号只发不收，补招的人往后编。
库里这些账号的 `phase` 一律是 `main`，阶段靠编号区分。
"""


MIRROR_ACCOUNT = re.compile(r"^ADMIN-(?P<lang>ZH|EN)-(?P<number>\d{2,})$")
"""管理员镜像号 `ADMIN-ZH-01` / `ADMIN-EN-01`（2026-09-29 版）。

队列照抄某位标注者，页面与标注者一比一；但不受训练关卡约束，可以在训练页与
正式页之间随意切换，训练复盘不等交齐就能看。给 Yoe 检查与修改界面用，
**它产生的任何数据都不是研究数据**。编号不以 `P` 开头，不会被 `plan` 取进去。
"""


def is_mirror(annotator_id: str) -> bool:
    return MIRROR_ACCOUNT.match(annotator_id) is not None


def stage_account_id(stage: int, language: str, number: int) -> str:
    return f"P{stage}-{language.upper()}-{number:02d}"


def stage_account_prefix(stage: int, language: str) -> str:
    return f"P{stage}-{language.upper()}-"

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
