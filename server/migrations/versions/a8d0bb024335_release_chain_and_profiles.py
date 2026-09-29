"""分配的释放与转移链；标注者档案（2026-09-29 版）

Revision ID: a8d0bb024335
Revises: d5f13c8ba204

阶段一每人 4,275 条，中途有人退出要能把他剩下的子任务转给补招的人，
而且**分配记录只追加、不删改**：

- `assignments` 加 `status`（active / released）、`released_at`、
  `release_event_id`（哪次操作释放的）、`replaces_assignment_id`（接手的新行
  指回被释放的旧行）
- `assignment_events`：每次释放 / 转移一行，记谁、何时、为什么、动了多少
- `annotator_profiles`：与账号一对一的个人档案（国籍、年龄等），只给管理员读
"""
from alembic import op
import sqlalchemy as sa

from app.models import JsonCol

revision = "a8d0bb024335"
down_revision = "d5f13c8ba204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assignment_events",
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("annotator_id", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("detail", JsonCol, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('release', 'transfer')", name="ck_assignment_events_kind"
        ),
        sa.ForeignKeyConstraint(
            ["annotator_id"], ["annotators.annotator_id"],
            name="fk_assignment_events_annotator",
        ),
        sa.PrimaryKeyConstraint("event_id", name="pk_assignment_events"),
    )

    # server_default 只为给存量行补值（线上已有的分配全部是 active）。
    # 模型上的缺省由 Python 侧给，两边都写会在改缺省时漏掉一处。
    with op.batch_alter_table("assignments") as batch:
        batch.add_column(
            sa.Column("status", sa.Text(), nullable=False, server_default="active")
        )
        batch.add_column(sa.Column("released_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("release_event_id", sa.Integer()))
        batch.add_column(sa.Column("replaces_assignment_id", sa.Integer()))
        batch.create_check_constraint(
            "ck_assignments_status", "status IN ('active', 'released')"
        )
        batch.create_foreign_key(
            "fk_assignments_release_event", "assignment_events",
            ["release_event_id"], ["event_id"],
        )
        batch.create_foreign_key(
            "fk_assignments_replaces", "assignments",
            ["replaces_assignment_id"], ["assignment_id"],
        )

    op.create_table(
        "annotator_profiles",
        sa.Column("annotator_id", sa.Text(), nullable=False),
        sa.Column("nationality", sa.Text()),
        sa.Column("age", sa.Integer()),
        sa.Column("gender", sa.Text()),
        sa.Column("native_language", sa.Text()),
        sa.Column("other_languages", sa.Text()),
        sa.Column("education", sa.Text()),
        sa.Column("contact", sa.Text()),
        sa.Column("recruited_at", sa.DateTime(timezone=True)),
        sa.Column("consent_at", sa.DateTime(timezone=True)),
        sa.Column("left_at", sa.DateTime(timezone=True)),
        sa.Column("left_reason", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("extra", JsonCol, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "age IS NULL OR (age > 0 AND age < 120)", name="ck_profiles_age"
        ),
        sa.ForeignKeyConstraint(
            ["annotator_id"], ["annotators.annotator_id"],
            name="fk_annotator_profiles_annotator",
        ),
        sa.PrimaryKeyConstraint("annotator_id", name="pk_annotator_profiles"),
    )


def downgrade() -> None:
    op.drop_table("annotator_profiles")
    with op.batch_alter_table("assignments") as batch:
        batch.drop_constraint("fk_assignments_replaces", type_="foreignkey")
        batch.drop_constraint("fk_assignments_release_event", type_="foreignkey")
        batch.drop_constraint("ck_assignments_status", type_="check")
        batch.drop_column("replaces_assignment_id")
        batch.drop_column("release_event_id")
        batch.drop_column("released_at")
        batch.drop_column("status")
    op.drop_table("assignment_events")
