"""V3：模态拆成五种，轮次带上维度与熟悉页播放次数

Revision ID: 3c1f5a90b7d2
Revises: 22a6741867d8

V3 的两处口径变化：

1. `visual` 拆成 `face`（只看脸）与 `body`（脸被遮住、只看身体），模态从四种变五种
2. 一轮只标一个维度，`attempts` 因此需要 `dimension`；同时记下熟悉页真正播了几遍

**这条迁移会拒绝在还留着二维范式数据的库上运行。** 老数据的 modality 是
`visual`、没有 dimension，放行就等于把新旧两种范式混在一张表里——而这两者在
认知负荷与维度耦合上根本不是一回事，混了之后分析时再也分不开。二维范式的
全部结果已存档在 `archive/2026-09-16-2d-paradigm/`（240 任务、23450 采样点、
带 SHA256SUMS），确认存档无误后清库再跑本迁移。
"""
from alembic import op
import sqlalchemy as sa

revision = "3c1f5a90b7d2"
down_revision = "22a6741867d8"
branch_labels = None
depends_on = None

NEW_MODALITIES = ("face", "body", "audio", "text", "audiovisual")
DIMENSIONS = ("valence", "arousal")


def _one_of(column: str, values) -> str:
    joined = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({joined})"


def _guard(conn) -> None:
    """留着旧范式数据就停下来，并说清楚该怎么处理。"""
    stale_tasks = conn.execute(
        sa.text("SELECT count(*) FROM tasks WHERE modality NOT IN :ok").bindparams(
            sa.bindparam("ok", value=NEW_MODALITIES, expanding=True)
        )
    ).scalar_one()
    stale_attempts = conn.execute(
        sa.text("SELECT count(*) FROM attempts WHERE modality NOT IN :ok").bindparams(
            sa.bindparam("ok", value=NEW_MODALITIES, expanding=True)
        )
    ).scalar_one()
    if stale_tasks or stale_attempts:
        raise RuntimeError(
            f"库里还有二维范式的数据（tasks {stale_tasks} 条、attempts {stale_attempts} 条 "
            f"的 modality 不在 {NEW_MODALITIES}）。新旧范式不能混在一张表里。\n"
            "二维范式结果已存档在 archive/2026-09-16-2d-paradigm/，"
            "核对存档无误后清空这些表再跑本迁移。"
        )


def upgrade() -> None:
    conn = op.get_bind()
    _guard(conn)

    # 全部收进 batch_alter_table：生产是 Postgres，测试是 SQLite，而 SQLite
    # 不支持 ALTER COLUMN DROP DEFAULT，batch 模式会替它重建表。
    with op.batch_alter_table("attempts") as batch:
        # 加列时给缺省值，免得 NOT NULL 与已有行打架；随即去掉缺省，
        # 强制之后每一轮都必须显式说明标的是哪个维度。
        batch.add_column(
            sa.Column("dimension", sa.Text(), nullable=False, server_default="valence")
        )
        batch.add_column(
            sa.Column(
                "familiarization_plays",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.alter_column("dimension", server_default=None)
        batch.alter_column("familiarization_plays", server_default=None)
        batch.drop_constraint("ck_attempts_modality", type_="check")
        batch.create_check_constraint(
            "ck_attempts_modality", _one_of("modality", NEW_MODALITIES)
        )
        batch.create_check_constraint(
            "ck_attempts_dimension", _one_of("dimension", DIMENSIONS)
        )
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("ck_tasks_modality", type_="check")
        batch.create_check_constraint(
            "ck_tasks_modality", _one_of("modality", NEW_MODALITIES)
        )


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("ck_tasks_modality", type_="check")
        batch.create_check_constraint(
            "ck_tasks_modality",
            _one_of("modality", ("visual", "audio", "text", "audiovisual")),
        )
    with op.batch_alter_table("attempts") as batch:
        batch.drop_constraint("ck_attempts_dimension", type_="check")
        batch.drop_constraint("ck_attempts_modality", type_="check")
        batch.create_check_constraint(
            "ck_attempts_modality",
            _one_of("modality", ("visual", "audio", "text", "audiovisual")),
        )
    op.drop_column("attempts", "familiarization_plays")
    op.drop_column("attempts", "dimension")
