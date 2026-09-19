"""标注者带语言标签；参考曲线独立成表

Revision ID: d5f13c8ba204
Revises: c4d9a1e5b207

两件事，都是训练页与分配约束的前置。

`annotators.language`：`zh` 表示中英都能读，`en` 表示只读英文。chsims 的
`text` 与 `audiovisual` 只能分给 `zh`——那两个模态要读懂中文，其余模态与
语言无关。缺省给 `en` 而不是 `zh`：漏设的人只会拿到与语言无关的子任务，
而误判成 `zh` 的人会拿到读不懂的中文文本，坏得无声无息。

`reference_traces`：训练时拿来和标注者自己的曲线对照的参考标注，按
(task_id, dimension) 一条。解释文字三语各一列，缺哪种语言在库里一眼可见。
"""
from alembic import op
import sqlalchemy as sa

revision = "d5f13c8ba204"
down_revision = "c4d9a1e5b207"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default 是给存量行补值用的。模型上没有这个默认值——
    # 新行的缺省由 Python 侧给，两边都写会在改缺省时漏掉一处。
    with op.batch_alter_table("annotators") as batch:
        batch.add_column(
            sa.Column("language", sa.Text(), nullable=False, server_default="en")
        )
        batch.create_check_constraint(
            "ck_annotators_language", "language IN ('en', 'zh')"
        )

    op.create_table(
        "reference_traces",
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("dimension", sa.Text(), nullable=False),
        sa.Column("samples", sa.JSON(), nullable=False),
        sa.Column("source_attempt_id", sa.Text(), nullable=True),
        sa.Column("note_en", sa.Text(), nullable=True),
        sa.Column("note_zh", sa.Text(), nullable=True),
        sa.Column("note_fi", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.task_id"], name="fk_reference_traces_task"
        ),
        sa.PrimaryKeyConstraint("task_id", "dimension", name="pk_reference_traces"),
        sa.CheckConstraint(
            "dimension IN ('valence', 'arousal')", name="ck_reference_traces_dimension"
        ),
    )


def downgrade() -> None:
    op.drop_table("reference_traces")
    with op.batch_alter_table("annotators") as batch:
        batch.drop_constraint("ck_annotators_language", type_="check")
        batch.drop_column("language")
