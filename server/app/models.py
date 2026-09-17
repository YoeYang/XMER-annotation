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


class SampleNumber(Base):
    """样本编号：标注者看得到的 S0001，与原始样本一一对应。

    **这是编号的唯一一套表。** 从前编号是 `tasks.display_id` 上的一个普通列，
    同一样本的五个任务各存一份——数据库拦不住「S0001 同时挂在两个样本上」，
    也拦不住「一个样本有两个号」，全靠约定维持，而约定被某次导入捅破了
    （前端演示数据 `public/tasks.json` 里的 DEMO 就占着正式表的 S0001）。
    现在主键管编号不重复、唯一约束管样本不重号，两条都由数据库兜底。

    编号**只发不收**：样本退出池子时保留原号并标 `retired`，空出来的号
    绝不重新发给新样本——老编号指向新样本的话，先前提交的结果会静悄悄
    对到错的样本上，而数据看起来毫无异样。
    """

    __tablename__ = "sample_numbers"

    display_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint(
            _one_of("status", ("active", "retired")), name="ck_sample_numbers_status"
        ),
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
    #
    # **是小数不是整数**：前端记的是「播完的圈数 + 当前这遍的进度」，
    # 「0.3 遍」这个说法本身就要求小数。定成整数会让每次提交都被 422 挡下，
    # 而客户端的重试队列把这一次失败放大成无限重试。
    familiarization_plays: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
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
