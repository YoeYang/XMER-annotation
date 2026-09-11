from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .timeutils import UtcDateTime


class TaskOut(BaseModel):
    """下发给标注者的任务。刻意不含 is_anchor——标注者不应分辨出哪些是锚点。"""

    model_config = ConfigDict(from_attributes=True)

    task_id: str
    media_id: str
    source_id: str
    title: str
    modality: str
    src: str
    duration: float
    target: str
    demo: bool
    timeline_origin: float
    speaker_ref_src: str | None
    speaker_name: str | None


class MeOut(BaseModel):
    annotator_id: str
    display_name: str | None
    phase: str
    tasks: list[TaskOut]


class AttemptIn(BaseModel):
    """attempt_id 走路径参数；annotator_id 由令牌决定，不接受客户端指定。"""

    task_id: str
    media_id: str
    modality: str
    mode: Literal["preview", "annotation"]
    status: Literal["recording", "paused", "completed", "interrupted"]
    task_snapshot: dict[str, Any]
    events: list[dict[str, Any]] = Field(default_factory=list)
    sample_rate_hz: int
    started_at: datetime
    completed_at: datetime | None = None


class AttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attempt_id: str
    task_id: str
    annotator_id: str
    media_id: str
    modality: str
    mode: str
    status: str
    sample_rate_hz: int
    started_at: UtcDateTime
    completed_at: UtcDateTime | None
    sample_count: int
    last_media_time: float


class ChunkIn(BaseModel):
    samples: list[dict[str, Any]]


class ChunkOut(BaseModel):
    stored: bool
    """False 表示该块此前已写入，本次重传被忽略——重试路径的正常结果，不是错误。"""
    chunk_index: int
    sample_count: int


class SubmitIn(BaseModel):
    submission_id: str


class SubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    submission_id: str
    task_id: str
    annotator_id: str
    attempt_id: str
    revision: int
    previous_submission_id: str | None
    submitted_at: UtcDateTime
    updated_at: UtcDateTime | None
