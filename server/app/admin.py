import secrets
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .assignments import replace_assignments, tasks_by_sample_modality
from .auth import get_session, hash_token, new_token
from .export import build_export
from .completion import completed_counts
from .models import Annotator, Assignment, Attempt, AttemptFlag, Submission
from .config import PHASES
from .timeutils import to_utc_iso

router = APIRouter(prefix="/api/admin")


def require_admin(
    request: Request, authorization: str | None = Header(default=None)
) -> None:
    expected = request.app.state.settings.admin_token
    if not expected:
        # 没配 token 就不是"人人可进"，而是整个管理端关闭
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "管理端未启用。")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "需要管理员令牌。")
    provided = authorization.removeprefix("Bearer ").strip()
    # 定长比较，避免用响应时间逐字符试出令牌
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "管理员令牌无效。")


def _iso(value: datetime | None) -> str | None:
    return to_utc_iso(value) if value else None


@router.get("/progress", dependencies=[Depends(require_admin)])
def read_progress(session: Session = Depends(get_session)) -> dict:
    """各标注者的进度总览。以任务为单位统计，不是以样本为单位。"""
    assigned = dict(
        session.execute(
            select(Assignment.annotator_id, func.count())
            .group_by(Assignment.annotator_id)
        ).all()
    )
    anchors = dict(
        session.execute(
            select(Assignment.annotator_id, func.count())
            .where(Assignment.is_anchor.is_(True))
            .group_by(Assignment.annotator_id)
        ).all()
    )
    # V3 的一个子任务要标两个维度，**两个都交了才算标完**。
    # 按 task_id 去重的话，只标了效价的子任务也会被算成完成——
    # 进度表看着漂亮，交上来的数据缺一半维度。
    done = completed_counts(session)
    # 交了但还没交齐两维的，单独列出来：这是催办时最该看的一列
    partial = dict(
        session.execute(
            select(
                Submission.annotator_id, func.count(func.distinct(Submission.task_id))
            ).group_by(Submission.annotator_id)
        ).all()
    )
    started = dict(
        session.execute(
            select(
                Attempt.annotator_id, func.count(func.distinct(Attempt.task_id))
            )
            .where(Attempt.mode == "annotation")
            .group_by(Attempt.annotator_id)
        ).all()
    )
    last_seen = dict(
        session.execute(
            select(Attempt.annotator_id, func.max(Attempt.server_received_at))
            .group_by(Attempt.annotator_id)
        ).all()
    )

    rows = []
    for annotator in session.scalars(
        select(Annotator).order_by(Annotator.phase, Annotator.annotator_id)
    ):
        aid = annotator.annotator_id
        rows.append(
            {
                "annotator_id": aid,
                "display_name": annotator.display_name,
                "phase": annotator.phase,
                "active": annotator.active,
                "assigned": assigned.get(aid, 0),
                "anchors": anchors.get(aid, 0),
                "started": started.get(aid, 0),
                "submitted": done.get(aid, 0),
                # 动过但两维还没齐的子任务数
                "in_progress": partial.get(aid, 0) - done.get(aid, 0),
                "last_activity": _iso(last_seen.get(aid)),
            }
        )
    return {
        "generated_at": to_utc_iso(datetime.now()),
        "annotators": rows,
        "totals": {
            "annotators": len(rows),
            "assigned": sum(r["assigned"] for r in rows),
            "submitted": sum(r["submitted"] for r in rows),
            "in_progress": sum(r["in_progress"] for r in rows),
        },
    }


@router.get("/export", dependencies=[Depends(require_admin)])
def export_all(
    annotator: str | None = None, session: Session = Depends(get_session)
) -> dict:
    """导出结果。

    带 `?annotator=` 时返回**与 V1 `ExportData` 完全一致**的单人导出，
    `scripts/plot_va_curves.py` 可直接读；不带参数时返回全部标注者的打包。
    """
    if annotator:
        row = session.get(Annotator, annotator)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "没有这个标注者。")
        return build_export(session, row)

    everyone = session.scalars(
        select(Annotator).order_by(Annotator.phase, Annotator.annotator_id)
    ).all()
    return {
        "schema_version": 1,
        "exported_at": to_utc_iso(datetime.now()),
        "storage": "cloud",
        "annotators": [build_export(session, row) for row in everyone],
    }


@router.get('/ui', include_in_schema=False)
def admin_ui() -> FileResponse:
    """管理页本身不鉴权——它只是一个空壳，令牌由使用者在页面里填，
    数据请求仍走上面那些带 require_admin 的接口。"""
    return FileResponse(Path(__file__).parent / 'static' / 'admin.html')


# --------------------------------------------------------------- 写操作（T7）


@router.post("/annotators", dependencies=[Depends(require_admin)])
def create_annotators(
    session: Session = Depends(get_session),
    count: int = Body(..., embed=True, ge=1, le=200),
    phase: str = Body(..., embed=True),
    prefix: str = Body("A", embed=True),
    display_name_prefix: str = Body("", embed=True),
    base_url: str = Body("", embed=True),
) -> dict:
    """批量建号。明文令牌**只在本次响应里出现一次**，服务器只存哈希。"""
    if phase not in PHASES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"阶段只能是 {PHASES}。")
    existing = set(session.scalars(select(Annotator.annotator_id)))
    created, skipped = [], []
    for number in range(1, count + 1):
        annotator_id = f"{prefix}-{number:02d}"
        if annotator_id in existing:
            skipped.append(annotator_id)
            continue
        token = new_token()
        session.add(
            Annotator(
                annotator_id=annotator_id,
                token_hash=hash_token(token),
                display_name=f"{display_name_prefix}{number:02d}"
                if display_name_prefix
                else None,
                phase=phase,
            )
        )
        created.append(
            {
                "annotator_id": annotator_id,
                "phase": phase,
                "token": token,
                "url": f"{base_url.rstrip('/')}/?t={token}" if base_url else None,
            }
        )
    session.commit()
    return {"created": created, "skipped": skipped}


@router.patch("/annotators/{annotator_id}", dependencies=[Depends(require_admin)])
def update_annotator(
    annotator_id: str,
    session: Session = Depends(get_session),
    active: bool | None = Body(None, embed=True),
    display_name: str | None = Body(None, embed=True),
) -> dict:
    annotator = session.get(Annotator, annotator_id)
    if annotator is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "没有这个标注者。")
    if active is not None:
        annotator.active = active
    if display_name is not None:
        annotator.display_name = display_name
    session.commit()
    return {
        "annotator_id": annotator.annotator_id,
        "active": annotator.active,
        "display_name": annotator.display_name,
    }


@router.put(
    "/assignments/{annotator_id}", dependencies=[Depends(require_admin)]
)
def set_assignments(
    annotator_id: str,
    session: Session = Depends(get_session),
    phase: str = Body(..., embed=True),
    queue: list[dict] = Body(..., embed=True),
) -> dict:
    """整体替换某人某阶段的队列。

    V3 起队列以**子任务**为单位，每项 `{sample_id, modality, is_anchor?}`，
    顺序即队列顺序。样本粒度表达不了硬隔离——同一样本的各模态要分给不同的人。
    """
    if session.get(Annotator, annotator_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "没有这个标注者。")
    if phase not in PHASES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"阶段只能是 {PHASES}。")
    written, missing = replace_assignments(
        session,
        annotator_id,
        phase,
        [
            (item["sample_id"], item["modality"], bool(item.get("is_anchor")))
            for item in queue
        ],
        tasks_by_sample_modality(session),
    )
    session.commit()
    return {"written": written, "missing_tasks": missing}


@router.get("/attempts", dependencies=[Depends(require_admin)])
def list_attempts(
    annotator: str | None = None, session: Session = Depends(get_session)
) -> list[dict]:
    """轮次列表，带当前处置标记，供管理端挑出要作废的那一轮。"""
    query = select(Attempt).order_by(Attempt.server_received_at.desc())
    if annotator:
        query = query.where(Attempt.annotator_id == annotator)
    latest_flag = {}
    for flag in session.scalars(select(AttemptFlag).order_by(AttemptFlag.flagged_at)):
        latest_flag[flag.attempt_id] = flag.flag
    return [
        {
            "attempt_id": a.attempt_id,
            "annotator_id": a.annotator_id,
            "task_id": a.task_id,
            "modality": a.modality,
            "mode": a.mode,
            "status": a.status,
            "sample_count": a.sample_count,
            "received_at": _iso(a.server_received_at),
            "flag": latest_flag.get(a.attempt_id),
        }
        for a in session.scalars(query)
    ]


@router.post("/attempts/{attempt_id}/flags", dependencies=[Depends(require_admin)])
def flag_attempt(
    attempt_id: str,
    session: Session = Depends(get_session),
    flag: str = Body(..., embed=True),
    note: str = Body("", embed=True),
    flagged_by: str = Body("admin", embed=True),
) -> dict:
    """标记轮次。作废是**追加一条处置记录**，不删数据——
    原始轨迹必须留着，判断错了还能翻案。"""
    if flag not in ("ok", "low_quality", "void"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "标记只能是 ok / low_quality / void。"
        )
    if session.get(Attempt, attempt_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "没有这个轮次。")
    session.add(
        AttemptFlag(
            attempt_id=attempt_id, flag=flag, note=note, flagged_by=flagged_by
        )
    )
    session.commit()
    return {"attempt_id": attempt_id, "flag": flag}
