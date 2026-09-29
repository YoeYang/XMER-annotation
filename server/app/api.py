from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import current_annotator, get_session
from .assignments import numbers_by_sample
from .completion import completed_tasks, latest_submissions
from .config import DIMENSIONS, MODALITIES
from .export import assemble_samples, build_export
from .models import (
    Annotator,
    Assignment,
    Attempt,
    ReferenceTrace,
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
    DebriefItemOut,
    DebriefOut,
    DebriefPairOut,
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


def _training_task_ids(session: Session, annotator: Annotator) -> list[str]:
    return list(
        session.scalars(
            select(Assignment.task_id).where(
                Assignment.annotator_id == annotator.annotator_id,
                Assignment.status == "active",
                Assignment.phase == "training",
            )
        )
    )


def current_phase(session: Session, annotator: Annotator) -> str:
    """这位标注者**此刻**在做哪一批分配（2026-09-29 版）。

    训练与正式是同一个账号：正式标注者（`phase=main`）名下同时挂着 training 与
    main 两批分配，训练交齐之前只发训练，交齐后（`trained_at` 写上）只发正式。
    没有训练分配的正式账号直接进正式。

    公用预览号（`phase=training`）永远停在训练，不会解锁。
    """
    if annotator.phase != "main" or annotator.trained_at is not None:
        return annotator.phase
    return "training" if _training_task_ids(session, annotator) else "main"


def _unlock_if_trained(session: Session, annotator: Annotator) -> str:
    """训练两维全部交齐就写 `trained_at`，自动解锁正式任务（Yoe 定：不要人工放行）。

    在 `/me` 里判定：标注者做完最后一条训练、页面重新加载时就拿到正式队列。
    返回判定之后的当前阶段。
    """
    phase = current_phase(session, annotator)
    if phase != "training" or annotator.phase != "main":
        return phase
    if set(_training_task_ids(session, annotator)) <= completed_tasks(
        session, annotator.annotator_id
    ):
        annotator.trained_at = datetime.now(timezone.utc)
        session.commit()
        return "main"
    return phase


def _assigned_task(session: Session, annotator: Annotator, task_id: str) -> Task:
    """访问隔离：标注者只能碰自己**当前阶段**分配到的任务。

    训练没交齐时碰不到正式任务，解锁后也碰不到训练任务——两批互不串。
    """
    task = session.scalar(
        select(Task)
        .join(Assignment, Assignment.task_id == Task.task_id)
        .where(
            Task.task_id == task_id,
            Assignment.annotator_id == annotator.annotator_id,
            Assignment.status == "active",
            Assignment.phase == current_phase(session, annotator),
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
    phase = _unlock_if_trained(session, annotator)
    rows = session.execute(
        select(Task, Assignment.order_index, SampleNumber.display_id)
        .join(Assignment, Assignment.task_id == Task.task_id)
        .outerjoin(SampleNumber, SampleNumber.source_id == Task.source_id)
        .where(
            Assignment.annotator_id == annotator.annotator_id,
            Assignment.status == "active",
            Assignment.phase == phase,
        )
        .order_by(Assignment.order_index, MODALITY_RANK)
    ).all()
    return MeOut(
        annotator_id=annotator.annotator_id,
        display_name=annotator.display_name,
        phase=phase,
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


def _points(samples: list[dict]) -> list[dict]:
    """采样点瘦身成画图要的两列。"""
    return [
        {"t": s.get("media_time"), "v": s.get("value")}
        for s in samples
        if s.get("is_valid", True)
    ]


@router.get("/training/debrief/{modality}", response_model=DebriefOut)
def read_debrief(
    modality: str,
    session: Session = Depends(get_session),
    annotator: Annotator = Depends(current_annotator),
):
    """一个模态段的复盘：这一段每条素材的两条曲线与参考曲线、以及解释。

    **按模态分段而不是每条一放**：一次看 11 条记不住，看完就忘；
    一次看两条、紧接着进入下一个模态，回顾的东西还在手上。

    **整段都交齐才放**，理由与单条那个接口相同——先看到参考曲线再标后面几条
    等于给了答案。这道闸在服务端，前端不显示拦不住直接请求接口的人。

    一次把素材、自己的曲线、参考曲线、解释全取齐：分几个接口的话，前端要自己
    按 task_id 把几份数据对起来，而对错了看不出来——曲线会画到别的样本下面。
    """
    if modality not in MODALITIES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "没有这个模态。")

    # 只看**训练分配**，与账号此刻在哪个阶段无关：做完最后一段训练时账号可能
    # 已经解锁，那一段的复盘照样要能看；正式任务则永远拿不到参考曲线。
    assigned = list(
        session.execute(
            select(Task, Assignment.order_index)
            .join(Assignment, Assignment.task_id == Task.task_id)
            .where(
                Assignment.annotator_id == annotator.annotator_id,
                Assignment.status == "active",
                Assignment.phase == "training",
                Task.modality == modality,
            )
            .order_by(Assignment.order_index)
        )
    )
    if not assigned:
        if not _training_task_ids(session, annotator):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "复盘只对训练任务提供。")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "这个模态没有分配给你的训练任务。")

    done = completed_tasks(session, annotator.annotator_id)
    pending = [task.task_id for task, _ in assigned if task.task_id not in done]
    if pending:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"这一段还有 {len(pending)} 条没标完，两个维度都提交后才能看对比。",
        )

    numbers = numbers_by_sample(session)
    latest = {
        (row.task_id, row.dimension): row
        for row in sorted(
            latest_submissions(session, annotator.annotator_id),
            key=lambda r: r.revision,
        )
    }
    references = {
        (row.task_id, row.dimension): row
        for row in session.scalars(
            select(ReferenceTrace).where(
                ReferenceTrace.task_id.in_([task.task_id for task, _ in assigned])
            )
        )
    }

    items = []
    for task, order_index in assigned:
        pairs = []
        for dimension in DIMENSIONS:
            submission = latest.get((task.task_id, dimension))
            reference = references.get((task.task_id, dimension))
            pairs.append(
                DebriefPairOut(
                    dimension=dimension,
                    mine=_points(assemble_samples(session, submission.attempt_id))
                    if submission
                    else [],
                    reference=_points(reference.samples) if reference else [],
                    note_en=reference.note_en if reference else None,
                    note_zh=reference.note_zh if reference else None,
                    note_fi=reference.note_fi if reference else None,
                )
            )
        items.append(
            DebriefItemOut(
                task_id=task.task_id,
                display_id=numbers.get(task.source_id),
                modality=task.modality,
                src=task.src,
                duration=task.duration,
                speaker_ref_src=task.speaker_ref_src,
                order_index=order_index,
                pairs=pairs,
            )
        )
    return DebriefOut(modality=modality, items=items)
