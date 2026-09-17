"""提交记录带上维度：效价与唤醒各走各的版本链

Revision ID: 7ae2d41c9f08
Revises: 3c1f5a90b7d2

`attempts` 在上一条迁移里已经有了 `dimension`，`submissions` 却没有，
唯一约束还是 `(annotator_id, task_id, revision)`。于是一个子任务的两个维度
被并进同一条链：交完效价再交唤醒，唤醒被记成 revision 2 并指回效价——
系统以为标注者改了效价，其实他标的是唤醒。完成度统计也跟着错，
只标了一半的子任务会被算成已完成。

Yoe 定的口径是两个维度**像纯视觉与纯语音那样彻底隔离**，一个样本
一个标注者产出 5 模态 × 2 维度 = 10 份独立记录。

SQLite 下改约束只能靠 `batch_alter_table` 建新表搬数据再丢旧表，而
`previous_submission_id` 指向本表，重建途中必然出现自引用的中间态——
所以本迁移在 SQLite 上要求外键校验处于默认的关闭状态。生产是 Postgres，
`ALTER TABLE ... DROP CONSTRAINT` 是原生操作、全程没有中间态，不受此限。

已有的提交从各自的轮次回填维度，再按 `(标注者, 子任务, 维度)` 重编
revision 与 previous 链——原来的编号是在错误的分组下算出来的，
直接留着会让两条链的版本号交错。
"""
from collections import defaultdict

from alembic import op
import sqlalchemy as sa

revision = "7ae2d41c9f08"
down_revision = "3c1f5a90b7d2"
branch_labels = None
depends_on = None

DIMENSIONS = ("valence", "arousal")


def _one_of(column: str, values) -> str:
    joined = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({joined})"


def _rechain(conn) -> None:
    """按 (标注者, 子任务, 维度) 重编 revision 与 previous 链。

    提交时间升序即版本先后。原编号来自 `(标注者, 子任务)` 这个错误的分组，
    照搬会让效价的 v1 后面跟着唤醒的 v2。
    """
    rows = conn.execute(
        sa.text(
            "SELECT submission_id, annotator_id, task_id, dimension, submitted_at "
            "FROM submissions ORDER BY submitted_at, submission_id"
        )
    ).fetchall()
    chains = defaultdict(list)
    for row in rows:
        chains[(row.annotator_id, row.task_id, row.dimension)].append(row.submission_id)

    for chain in chains.values():
        previous = None
        for number, submission_id in enumerate(chain, start=1):
            conn.execute(
                sa.text(
                    "UPDATE submissions SET revision = :rev, "
                    "previous_submission_id = :prev WHERE submission_id = :sid"
                ),
                {"rev": number, "prev": previous, "sid": submission_id},
            )
            previous = submission_id


def upgrade() -> None:
    conn = op.get_bind()

    # 先加成可空列并回填，再收紧为 NOT NULL：维度的唯一可信来源是轮次本身，
    # 给一个 server_default 等于给了错误的默认答案。
    with op.batch_alter_table("submissions") as batch:
        batch.add_column(sa.Column("dimension", sa.Text(), nullable=True))

    conn.execute(
        sa.text(
            "UPDATE submissions SET dimension = "
            "(SELECT a.dimension FROM attempts a "
            " WHERE a.attempt_id = submissions.attempt_id)"
        )
    )
    orphans = conn.execute(
        sa.text("SELECT count(*) FROM submissions WHERE dimension IS NULL")
    ).scalar_one()
    if orphans:
        raise RuntimeError(
            f"有 {orphans} 条提交找不到对应轮次的维度，无法回填。"
            "先查清这些提交为什么没有轮次，再跑本迁移。"
        )
    # 旧唯一约束必须先卸掉再重编号：重编号中途两条链的版本号会短暂撞车
    # （唤醒的 2 降为 1、效价的 3 降为 2，而降到一半时 2 还被占着）。
    with op.batch_alter_table("submissions") as batch:
        batch.drop_constraint("uq_submissions_revision", type_="unique")

    _rechain(conn)

    with op.batch_alter_table("submissions") as batch:
        batch.alter_column("dimension", nullable=False)
        batch.create_unique_constraint(
            "uq_submissions_revision",
            ["annotator_id", "task_id", "dimension", "revision"],
        )
        batch.create_check_constraint(
            "ck_submissions_dimension", _one_of("dimension", DIMENSIONS)
        )


def downgrade() -> None:
    with op.batch_alter_table("submissions") as batch:
        batch.drop_constraint("ck_submissions_dimension", type_="check")
        batch.drop_constraint("uq_submissions_revision", type_="unique")
        batch.create_unique_constraint(
            "uq_submissions_revision", ["annotator_id", "task_id", "revision"]
        )
        batch.drop_column("dimension")
