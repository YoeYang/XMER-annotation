from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import current_annotator, get_session
from .config import MODALITIES
from .export import assemble_samples, build_export
from .models import (
    Annotator,
    Assignment,
    Attempt,
    SampleChunk,
    SampleNumber,
    Submission,
    Task,
)
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

# 次级排序。order_index 相同时若不定义先后，数据库返回的顺序是未定义的——
# 而客户端的默认选中与「下一条」都跟着这个顺序走，等于把防污染的排序绕过去。
# 直接由 config.MODALITIES 的次序生成，避免这里和常量表各写一份而漂移。
MODALITY_RANK = case(
    *[(Task.modality == m, i) for i, m in enumerate(MODALITIES)],
    else_=len(MODALITIES),
)


def _task_out(task: Task, order_index: int, display_id: str | None) -> TaskOut:
    """把任务和它在这位标注者队列里的位置拼成一条下发记录。

    字段从 TaskOut 的定义反查，不手抄一遍——手抄的那份迟早和 schema 漂移。
    编号来自 `sample_numbers`（那是唯一一套），随查询连出来传进这里。
    """
    derived = {"order_index", "display_id"}
    fields = {
        name: getattr(task, name)
        for name in TaskOut.model_fields
        if name not in derived
    }
    return TaskOut(**fields, order_index=order_index, display_id=display_id)


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


def _latest_submission(
    session: Session, annotator: Annotator, attempt: Attempt
) -> Submission | None:
    """该标注者在这个子任务的**这个维度**上最近一次提交。

    维度必须进条件。少了它，效价与唤醒会被并进同一条版本链，
    第二个维度凭空变成第一个维度的修订版。
    """
    return session.scalars(
        select(Submission)
        .where(
            Submission.annotator_id == annotator.annotator_id,
            Submission.task_id == attempt.task_id,
            Submission.dimension == attempt.dimension,
        )
        .order_by(Submission.revision.desc())
    ).first()


@router.get("/me", response_model=MeOut)
def read_me(
    annotator: Annotator = Depends(current_annotator),
    session: Session = Depends(get_session),
) -> MeOut:
    # order_index 挂在 assignments 上而不是 tasks 上——同一个任务分给不同的人，
    # 队列位置本来就不同。所以要连着取出来，再拼进 TaskOut。
    # 编号走外连接：没发号的样本照常下发，只是目录里没有编号可显示，
    # 比整条任务凭空消失容易察觉得多。
    rows = session.execute(
        select(Task, Assignment.order_index, SampleNumber.display_id)
        .join(Assignment, Assignment.task_id == Task.task_id)
        .outerjoin(SampleNumber, SampleNumber.source_id == Task.source_id)
        .where(
            Assignment.annotator_id == annotator.annotator_id,
            Assignment.phase == annotator.phase,
        )
        .order_by(Assignment.order_index, MODALITY_RANK)
    ).all()
    return MeOut(
        annotator_id=annotator.annotator_id,
        display_name=annotator.display_name,
        phase=annotator.phase,
        tasks=[
            _task_out(task, order_index, display_id)
            for task, order_index, display_id in rows
        ],
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


@router.get("/attempts/{attempt_id}/samples")
def read_samples(
    attempt_id: str,
    annotator: Annotator = Depends(current_annotator),
    session: Session = Depends(get_session),
) -> list[dict]:
    """读回某一轮的全部采样点，按 sample_index 排好。

    标注页在四个模态都提交后，要把这个样本的四条曲线画在罗盘下方；
    换设备或刷新之后本地内存里没有采样点，只能回服务器取。
    """
    _own_attempt(session, annotator, attempt_id)
    return assemble_samples(session, attempt_id)


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

    # 版本链按**维度**各走各的：效价的上一版是效价，不是刚交的唤醒。
    previous = _latest_submission(session, annotator, attempt)

    now = datetime.now(timezone.utc)
    submission = Submission(
        submission_id=payload.submission_id,
        task_id=attempt.task_id,
        annotator_id=annotator.annotator_id,
        attempt_id=attempt_id,
        dimension=attempt.dimension,
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
        winner = _latest_submission(session, annotator, attempt)
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
