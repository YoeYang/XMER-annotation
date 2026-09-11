from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import current_annotator, get_session
from .export import assemble_samples, build_export
from .models import Annotator, Assignment, Attempt, SampleChunk, Submission, Task
from .schemas import (
    AttemptIn,
    AttemptOut,
    ChunkIn,
    ChunkOut,
    MeOut,
    SubmissionOut,
    SubmitIn,
    TaskOut,
)

router = APIRouter(prefix="/api")


def _assigned_task(session: Session, annotator: Annotator, task_id: str) -> Task:
    """访问隔离：标注者只能碰自己当前阶段分配到的任务。"""
    task = session.scalar(
        select(Task)
        .join(Assignment, Assignment.task_id == Task.task_id)
        .where(
            Task.task_id == task_id,
            Assignment.annotator_id == annotator.annotator_id,
            Assignment.phase == annotator.phase,
        )
    )
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该样本未分配给你。")
    return task


def _own_attempt(session: Session, annotator: Annotator, attempt_id: str) -> Attempt:
    attempt = session.get(Attempt, attempt_id)
    if attempt is None or attempt.annotator_id != annotator.annotator_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到该标注轮次。")
    return attempt


@router.get("/me", response_model=MeOut)
def read_me(
    annotator: Annotator = Depends(current_annotator),
    session: Session = Depends(get_session),
) -> MeOut:
    tasks = session.scalars(
        select(Task)
        .join(Assignment, Assignment.task_id == Task.task_id)
        .where(
            Assignment.annotator_id == annotator.annotator_id,
            Assignment.phase == annotator.phase,
        )
        .order_by(Assignment.order_index)
    ).all()
    return MeOut(
        annotator_id=annotator.annotator_id,
        display_name=annotator.display_name,
        phase=annotator.phase,
        tasks=[TaskOut.model_validate(t) for t in tasks],
    )


@router.put("/attempts/{attempt_id}", response_model=AttemptOut)
def upsert_attempt(
    attempt_id: str,
    payload: AttemptIn,
    annotator: Annotator = Depends(current_annotator),
    session: Session = Depends(get_session),
) -> AttemptOut:
    """幂等：attempt_id 由客户端生成，重复 PUT 只是覆盖元数据。"""
    _assigned_task(session, annotator, payload.task_id)
    attempt = session.get(Attempt, attempt_id)

    if attempt is None:
        attempt = Attempt(
            attempt_id=attempt_id,
            annotator_id=annotator.annotator_id,
            sample_count=0,
            last_media_time=0.0,
            **payload.model_dump(),
        )
        session.add(attempt)
    else:
        if attempt.annotator_id != annotator.annotator_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到该标注轮次。")
        for field, value in payload.model_dump().items():
            setattr(attempt, field, value)

    session.commit()
    return AttemptOut.model_validate(attempt)


@router.put("/attempts/{attempt_id}/chunks/{chunk_index}", response_model=ChunkOut)
def write_chunk(
    attempt_id: str,
    chunk_index: int,
    payload: ChunkIn,
    annotator: Annotator = Depends(current_annotator),
    session: Session = Depends(get_session),
) -> ChunkOut:
    """幂等写入：同一块重传直接忽略，不产生重复采样，也不报错。"""
    attempt = _own_attempt(session, annotator, attempt_id)
    if chunk_index < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "块序号不能为负。")

    existing = session.get(SampleChunk, (attempt_id, chunk_index))
    stored = existing is None
    if stored:
        session.add(
            SampleChunk(
                attempt_id=attempt_id, chunk_index=chunk_index, samples=payload.samples
            )
        )
        session.flush()

    # 以库中实际内容为准重算进度，即使某次元数据 PUT 丢失也能自愈
    samples = assemble_samples(session, attempt_id)
    attempt.sample_count = len(samples)
    if samples:
        attempt.last_media_time = max(s.get("media_time", 0.0) for s in samples)
    session.commit()

    return ChunkOut(
        stored=stored, chunk_index=chunk_index, sample_count=attempt.sample_count
    )


@router.post("/attempts/{attempt_id}/submit", response_model=SubmissionOut)
def submit_attempt(
    attempt_id: str,
    payload: SubmitIn,
    annotator: Annotator = Depends(current_annotator),
    session: Session = Depends(get_session),
) -> SubmissionOut:
    """提交形成新版本而非覆盖；重放同一 submission_id 返回既有记录。"""
    attempt = _own_attempt(session, annotator, attempt_id)

    replay = session.get(Submission, payload.submission_id)
    if replay is not None:
        if replay.annotator_id != annotator.annotator_id:
            raise HTTPException(status.HTTP_409_CONFLICT, "提交编号已被占用。")
        return SubmissionOut.model_validate(replay)

    # 一轮次一提交：换个 submission_id 重发不能凭空生成新版本。
    # 重标要另开轮次，那才是 Update 的正当路径。
    already = session.scalar(
        select(Submission).where(Submission.attempt_id == attempt_id)
    )
    if already is not None:
        return SubmissionOut.model_validate(already)

    if attempt.mode != "annotation":
        raise HTTPException(status.HTTP_409_CONFLICT, "预览轮次不能提交。")
    if attempt.status != "completed":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "该轮次尚未标注完成，请播放至结束后再提交。"
        )

    previous = session.scalars(
        select(Submission)
        .where(
            Submission.annotator_id == annotator.annotator_id,
            Submission.task_id == attempt.task_id,
        )
        .order_by(Submission.revision.desc())
    ).first()

    now = datetime.now(timezone.utc)
    submission = Submission(
        submission_id=payload.submission_id,
        task_id=attempt.task_id,
        annotator_id=annotator.annotator_id,
        attempt_id=attempt_id,
        revision=previous.revision + 1 if previous else 1,
        previous_submission_id=previous.submission_id if previous else None,
        submitted_at=now,
        updated_at=now if previous else None,
    )
    session.add(submission)
    try:
        session.commit()
    except IntegrityError:
        # 并发双提交：唯一约束挡下后者，返回先落库的那条
        session.rollback()
        winner = session.scalars(
            select(Submission)
            .where(
                Submission.annotator_id == annotator.annotator_id,
                Submission.task_id == attempt.task_id,
            )
            .order_by(Submission.revision.desc())
        ).first()
        return SubmissionOut.model_validate(winner)

    return SubmissionOut.model_validate(submission)


@router.get("/attempts", response_model=list[AttemptOut])
def list_attempts(
    annotator: Annotator = Depends(current_annotator),
    session: Session = Depends(get_session),
) -> list[AttemptOut]:
    rows = session.scalars(
        select(Attempt)
        .where(Attempt.annotator_id == annotator.annotator_id)
        .order_by(Attempt.started_at)
    ).all()
    return [AttemptOut.model_validate(r) for r in rows]


@router.get("/submissions", response_model=list[SubmissionOut])
def list_submissions(
    annotator: Annotator = Depends(current_annotator),
    session: Session = Depends(get_session),
) -> list[SubmissionOut]:
    rows = session.scalars(
        select(Submission)
        .where(Submission.annotator_id == annotator.annotator_id)
        .order_by(Submission.submitted_at)
    ).all()
    return [SubmissionOut.model_validate(r) for r in rows]


@router.get("/export")
def export_own_data(
    annotator: Annotator = Depends(current_annotator),
    session: Session = Depends(get_session),
) -> dict:
    return build_export(session, annotator)
