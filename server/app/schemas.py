from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .timeutils import UtcDateTime


class TaskOut(BaseModel):
    """下发给标注者的任务。

    刻意不含三样东西：
    is_anchor —— 标注者不应分辨出哪些是锚点；
    source_id 与 title —— 两者都含数据集名和原始编号，会透露样本来源。
    目录里显示的是 display_id。
    """

    model_config = ConfigDict(from_attributes=True)

    task_id: str
    media_id: str
    display_id: str | None
    modality: str
    src: str
    duration: float
    target: str
    demo: bool
    timeline_origin: float
    # 该标注者分配队列里的顺序。前端按模态分块后用它算「面部 3/20」这种
    # 块内序号——序号只在渲染时算，不落库，也不进导出。
    order_index: int
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
    dimension: Literal["valence", "arousal"]
    familiarization_plays: int = 0
    status: Literal["recording", "paused", "completed", "interrupted"]
    task_snapshot: dict[str, Any]
    events: list[dict[str, Any]] = Field(default_factory=list)
    sample_rate_hz: int
    started_at: datetime
    completed_at: datetime | None = None


class AttemptOut(BaseModel):
    """字段与前端 `Attempt` 类型一一对应，供跨设备恢复时直接还原。"""

    model_config = ConfigDict(from_attributes=True)

    schema_version: Literal[1] = 1
    attempt_id: str
    task_id: str
    annotator_id: str
    media_id: str
    modality: str
    mode: str
    dimension: str
    familiarization_plays: int
    status: str
    task_snapshot: dict[str, Any]
    sample_rate_hz: int
    started_at: UtcDateTime
    completed_at: UtcDateTime | None
    sample_count: int
    last_media_time: float
    events: list[dict[str, Any]]
    calibration: None = None


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
    dimension: str
    revision: int
    previous_submission_id: str | None
    submitted_at: UtcDateTime
    updated_at: UtcDateTime | None
