from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .completion import superseded_ids
from .models import Annotator, Attempt, SampleChunk, Submission
from .timeutils import to_utc_iso


def _iso(value: datetime | None) -> str | None:
    return to_utc_iso(value) if value else None


def assemble_samples(session: Session, attempt_id: str) -> list[dict[str, Any]]:
    """按 chunk_index 升序拼接采样块，还原完整轨迹。"""
    chunks = session.scalars(
        select(SampleChunk)
        .where(SampleChunk.attempt_id == attempt_id)
        .order_by(SampleChunk.chunk_index)
    ).all()
    return [sample for chunk in chunks for sample in chunk.samples]


def build_export(session: Session, annotator: Annotator) -> dict[str, Any]:
    """产出与 V1 `ExportData` 结构一致的导出，使现有分析脚本零改动可用。"""
    attempts = session.scalars(
        select(Attempt)
        .where(Attempt.annotator_id == annotator.annotator_id)
        .order_by(Attempt.started_at)
    ).all()
    submissions = session.scalars(
        select(Submission)
        .where(Submission.annotator_id == annotator.annotator_id)
        .order_by(Submission.submitted_at)
    ).all()
    # 被更新版本顶替的旧版：全部留在导出里（重标过几次是质检信号），
    # 但打上标记，分析脚本一眼就能跳过，不必自己重算版本链。
    stale = superseded_ids(session, annotator.annotator_id)

    return {
        "schema_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "storage": "cloud",
        "annotator_id": annotator.annotator_id,
        # 云端导出以服务器确认为准，不存在"尚未落盘"的尾部
        "unsaved_attempt_ids": [],
        "attempts": [
            {
                "schema_version": 1,
                "attempt_id": a.attempt_id,
                "task_id": a.task_id,
                "annotator_id": a.annotator_id,
                "media_id": a.media_id,
                "modality": a.modality,
                "mode": a.mode,
                "dimension": a.dimension,
                "familiarization_plays": a.familiarization_plays,
                "status": a.status,
                "task_snapshot": a.task_snapshot,
                "sample_rate_hz": a.sample_rate_hz,
                "started_at": _iso(a.started_at),
                "completed_at": _iso(a.completed_at),
                "sample_count": a.sample_count,
                "last_media_time": a.last_media_time,
                "events": a.events,
                "calibration": None,
                "samples": assemble_samples(session, a.attempt_id),
            }
            for a in attempts
        ],
        "submissions": [
            {
                "submission_id": s.submission_id,
                "task_id": s.task_id,
                "annotator_id": s.annotator_id,
                "attempt_id": s.attempt_id,
                # 效价与唤醒是两条独立的链，各自从 revision 1 开始
                "dimension": s.dimension,
                "revision": s.revision,
                "superseded": s.submission_id in stale,
                "previous_submission_id": s.previous_submission_id,
                "submitted_at": _iso(s.submitted_at),
                "updated_at": _iso(s.updated_at),
            }
            for s in submissions
        ],
    }
