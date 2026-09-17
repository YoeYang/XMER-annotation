"""熟悉页播放次数改为小数

Revision ID: c4d9a1e5b207
Revises: 9b4e07d2c513

`familiarization_plays` 记的是「播完的圈数 + 当前这遍的进度」，本来就是
小数——`models.py` 的注释自己写着「只播 0.3 遍就上手的人要单独看」，
而 0.3 遍存不进整数列。

定成整数的后果不止是丢精度：前端每次提交轮次都被 422 挡下，
客户端的重试队列再把这一次失败放大成无限重试。线上实测 321 个 422，
标注数据一条也没能上传，而界面上看不出来——直到有人去翻服务器日志。
"""
from alembic import op
import sqlalchemy as sa

revision = "c4d9a1e5b207"
down_revision = "9b4e07d2c513"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("attempts") as batch:
        batch.alter_column(
            "familiarization_plays",
            existing_type=sa.Integer(),
            type_=sa.Float(),
            existing_nullable=False,
        )


def downgrade() -> None:
    # 回退会把小数截成整数，0.3 遍变成 0 遍——这是有损的
    with op.batch_alter_table("attempts") as batch:
        batch.alter_column(
            "familiarization_plays",
            existing_type=sa.Float(),
            type_=sa.Integer(),
            existing_nullable=False,
            postgresql_using="familiarization_plays::integer",
        )
