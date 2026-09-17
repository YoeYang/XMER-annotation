from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .config import DIMENSIONS, MODALITIES, PHASES
from .db import Base

# 生产库用 JSONB（更紧凑、解析更快）；测试跑 SQLite 时退回通用 JSON
JsonCol = JSON().with_variant(JSONB, "postgresql")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _one_of(column: str, values: tuple[str, ...]) -> str:
    allowed = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({allowed})"


class Annotator(Base):
    __tablename__ = "annotators"

    annotator_id: Mapped[str] = mapped_column(Text, primary_key=True)
    # 只存哈希，明文 token 仅在生成链接时出现一次
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    phase: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    trained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint(_one_of("phase", PHASES), name="ck_annotators_phase"),
    )


class Task(Base):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(Text, primary_key=True)
    media_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    # 给标注者看的不透明编号（S0001…），同一样本的四个任务共用一个。
    # 目录里出现 meld / iemocap 这类名字会透露数据来源，也会让人对样本先入为主。
    # 由 manage.py assign-display-ids 填充，映射表只留在后台 CSV 里。
    display_id: Mapped[str | None] = mapped_column(Text, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    modality: Mapped[str] = mapped_column(Text, nullable=False)
    src: Mapped[str] = mapped_column(Text, nullable=False)
    duration: Mapped[float] = mapped_column(Float, nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False, default="")
    demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timeline_origin: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # 说话人静帧参考，由数据集预处理流水线产出，标注时常驻展示
    speaker_ref_src: Mapped[str | None] = mapped_column(Text)
    speaker_name: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(_one_of("modality", MODALITIES), name="ck_tasks_modality"),
    )


class Assignment(Base):
    __tablename__ = "assignments"

    assignment_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    annotator_id: Mapped[str] = mapped_column(
        Text, ForeignKey("annotators.annotator_id"), nullable=False
    )
    task_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tasks.task_id"), nullable=False
    )
    phase: Mapped[str] = mapped_column(Text, nullable=False)
    # 队列顺序；锚点按此散布插入队列内部，标注者无从分辨
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    is_anchor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "annotator_id", "task_id", "phase", name="uq_assignments_annotator_task"
        ),
        CheckConstraint(_one_of("phase", PHASES), name="ck_assignments_phase"),
    )


class Attempt(Base):
    __tablename__ = "attempts"

    attempt_id: Mapped[str] = mapped_column(Text, primary_key=True)
    task_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tasks.task_id"), nullable=False
    )
    annotator_id: Mapped[str] = mapped_column(
        Text, ForeignKey("annotators.annotator_id"), nullable=False
    )
    media_id: Mapped[str] = mapped_column(Text, nullable=False)
    modality: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    # V3：一轮只标一个维度。效价轮与唤醒轮是两条独立的 attempt，
    # 两者都提交了这个子任务才算完成。
    dimension: Mapped[str] = mapped_column(Text, nullable=False)
    # 熟悉页真正播了几遍。既是流程记录，也是质检信号——
    # 只播 0.3 遍就上手的人，后续标注质量要单独看。
    familiarization_plays: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    task_snapshot: Mapped[dict] = mapped_column(JsonCol, nullable=False)
    events: Mapped[list] = mapped_column(JsonCol, nullable=False, default=list)
    sample_rate_hz: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_media_time: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    server_received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint(_one_of("modality", MODALITIES), name="ck_attempts_modality"),
        CheckConstraint(
            _one_of("dimension", DIMENSIONS), name="ck_attempts_dimension"
        ),
        CheckConstraint(
            _one_of("mode", ("preview", "annotation")), name="ck_attempts_mode"
        ),
        CheckConstraint(
            _one_of("status", ("recording", "paused", "completed", "interrupted")),
            name="ck_attempts_status",
        ),
    )


class SampleChunk(Base):
    """一次 checkpoint 写入一块，追加式、永不重写。

    主键 (attempt_id, chunk_index) 即幂等键：断网重传同一块直接冲突忽略，
    不会产生重复采样。导出时按 chunk_index 升序拼接还原完整轨迹。
    """

    __tablename__ = "sample_chunks"

    attempt_id: Mapped[str] = mapped_column(
        Text, ForeignKey("attempts.attempt_id"), primary_key=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    samples: Mapped[list] = mapped_column(JsonCol, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class Submission(Base):
    __tablename__ = "submissions"

    submission_id: Mapped[str] = mapped_column(Text, primary_key=True)
    task_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tasks.task_id"), nullable=False
    )
    annotator_id: Mapped[str] = mapped_column(
        Text, ForeignKey("annotators.annotator_id"), nullable=False
    )
    attempt_id: Mapped[str] = mapped_column(
        Text, ForeignKey("attempts.attempt_id"), nullable=False
    )
    # V3：效价与唤醒是**两条独立的链**，像纯视觉与纯语音那样彻底隔开。
    # 取自轮次自身而非客户端另报一次——两处各报一次迟早对不上。
    # 没有这一列，交完效价再交唤醒会被记成效价的修订版：
    # 系统以为标注者改了效价，其实他标的是唤醒。
    dimension: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    # 版本链：Update 形成新记录并指回上一版，历史轨迹不被覆盖
    previous_submission_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("submissions.submission_id")
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "annotator_id", "task_id", "dimension", "revision",
            name="uq_submissions_revision",
        ),
        CheckConstraint(
            _one_of("dimension", DIMENSIONS), name="ck_submissions_dimension"
        ),
        # 一个轮次只能提交一次；重标要另开轮次，由此形成新版本
        UniqueConstraint("attempt_id", name="uq_submissions_attempt"),
    )


class AttemptFlag(Base):
    """管理端的作废与质量标记；保留历史，同一轮次可被多次标记。"""

    __tablename__ = "attempt_flags"

    flag_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempt_id: Mapped[str] = mapped_column(
        Text, ForeignKey("attempts.attempt_id"), nullable=False
    )
    flag: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    flagged_by: Mapped[str | None] = mapped_column(Text)
    flagged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint(
            _one_of("flag", ("ok", "low_quality", "void")), name="ck_attempt_flags_flag"
        ),
    )
