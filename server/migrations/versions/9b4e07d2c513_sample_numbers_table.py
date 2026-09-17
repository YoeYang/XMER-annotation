"""样本编号独立成表：一份真相，一一对应由数据库保证

Revision ID: 9b4e07d2c513
Revises: 7ae2d41c9f08

编号原先是 `tasks.display_id` 上的一个普通列，同一样本的五个任务各存一份。
数据库因此拦不住两件事：一个编号挂到两个样本上，一个样本拿到两个编号。
唯一性全靠约定，而约定已经被捅破过——前端演示数据 `public/tasks.json` 里的
DEMO 就占着正式表的 S0001 与 S0002。

现在编号搬进 `sample_numbers`：`display_id` 主键管「编号不重复」，
`source_id` 唯一约束管「样本不重号」，`tasks` 不再存副本。下发任务时
按 `source_id` 连出编号。

`status` 记录退役：样本退出池子时保留原号标 `retired`，空出来的号
绝不重新发给新样本——老编号指向新样本的话，先前提交的结果会静悄悄
对到错的样本上，而数据看起来毫无异样。
"""
from alembic import op
import sqlalchemy as sa

revision = "9b4e07d2c513"
down_revision = "7ae2d41c9f08"
branch_labels = None
depends_on = None

STATUSES = ("active", "retired")


def upgrade() -> None:
    conn = op.get_bind()

    op.create_table(
        "sample_numbers",
        sa.Column("display_id", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("display_id", name="pk_sample_numbers"),
        sa.UniqueConstraint("source_id", name="uq_sample_numbers_source"),
        sa.CheckConstraint(
            "status IN ('active', 'retired')", name="ck_sample_numbers_status"
        ),
    )

    # 搬家前先验：同一个编号挂在两个样本上的话，搬进新表会撞主键。
    # 与其让约束报一句看不懂的话，不如在这里说清楚是哪几个编号。
    clashes = conn.execute(
        sa.text(
            "SELECT display_id, count(DISTINCT source_id) AS n FROM tasks "
            "WHERE display_id IS NOT NULL GROUP BY display_id HAVING n > 1"
        )
    ).fetchall()
    if clashes:
        raise RuntimeError(
            f"有 {len(clashes)} 个编号挂在多个样本上，无法搬进唯一编号表："
            f"{[row[0] for row in clashes][:5]}。先查清这些编号的来源，"
            "确定每个号该归谁，再跑本迁移。"
        )
    doubles = conn.execute(
        sa.text(
            "SELECT source_id, count(DISTINCT display_id) AS n FROM tasks "
            "WHERE display_id IS NOT NULL GROUP BY source_id HAVING n > 1"
        )
    ).fetchall()
    if doubles:
        raise RuntimeError(
            f"有 {len(doubles)} 个样本挂着多个编号：{[row[0] for row in doubles][:5]}。"
            "编号必须一一对应，先定下每个样本留哪个号再跑本迁移。"
        )

    conn.execute(
        sa.text(
            "INSERT INTO sample_numbers (display_id, source_id, status, issued_at) "
            "SELECT DISTINCT display_id, source_id, 'active', CURRENT_TIMESTAMP "
            "FROM tasks WHERE display_id IS NOT NULL"
        )
    )

    # 索引要先显式丢掉：SQLite 上 batch 模式靠重建表来删列，重建时会照着
    # 旧定义重造索引，而索引指向的列已经不在了。
    op.drop_index("ix_tasks_display_id", table_name="tasks")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("display_id")


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("display_id", sa.Text(), nullable=True))
    op.create_index("ix_tasks_display_id", "tasks", ["display_id"])
    op.get_bind().execute(
        sa.text(
            "UPDATE tasks SET display_id = (SELECT n.display_id FROM sample_numbers n "
            "WHERE n.source_id = tasks.source_id)"
        )
    )
    op.drop_table("sample_numbers")
