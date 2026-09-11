import secrets
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import get_session
from .export import build_export
from .models import Annotator, Assignment, Attempt, Submission
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
    # 一个任务可能有多个版本的提交，按 task_id 去重才是"完成了多少任务"
    done = dict(
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
