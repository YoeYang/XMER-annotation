import secrets
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .assignments import (
    purge_annotator,
    replace_assignments,
    tasks_by_sample_modality,
)
from .auth import get_session, hash_token, new_token
from .export import build_export
from .completion import completed_counts
from .models import (
    Annotator,
    Assignment,
    Attempt,
    AttemptFlag,
    SampleNumber,
    Submission,
    Task,
)
from .config import MODALITIES, PHASES
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
    tickets = _tickets(session, annotator)
    attempts = list(session.scalars(query))
    rounds = _rounds(session, annotator)
    revisions = {
        attempt_id: revision
        for attempt_id, revision in session.execute(select(
            Submission.attempt_id, Submission.revision
        ))
    }
    return [
        {
            "attempt_id": a.attempt_id,
            "annotator_id": a.annotator_id,
            "task_id": a.task_id,
            # 标注者侧栏上看到的编号，报问题时用得上
            "ticket": tickets.get((a.annotator_id, a.task_id)),
            "modality": a.modality,
            "mode": a.mode,
            "dimension": a.dimension,
            # 这个人对这条样本这个维度标的第几遍，以及是不是当前有效的那遍
            "attempt_no": rounds[a.attempt_id][0],
            "attempt_total": rounds[a.attempt_id][1],
            "is_current": rounds[a.attempt_id][0] == rounds[a.attempt_id][1],
            "revision": revisions.get(a.attempt_id),
            "status": a.status,
            "sample_count": a.sample_count,
            "received_at": _iso(a.server_received_at),
            "flag": latest_flag.get(a.attempt_id),
        }
        for a in attempts
    ]


def _rounds(
    session: Session, annotator: str | None
) -> dict[str, tuple[int, int]]:
    """轮次 → (这是第几遍, 一共标了几遍)。

    按 `(标注者, 任务, 维度)` 分组、开始时间排序。重标会形成新轮次而不是
    覆盖旧的，处置时必须分得清哪遍是最新：把当前有效的那遍作废掉，
    等于把这条样本的数据废了，而想废的往往恰恰是早先那几遍。

    没提交的轮次也编号——否则表上看不出它夹在哪两遍之间。
    """
    query = select(
        Attempt.attempt_id, Attempt.annotator_id, Attempt.task_id,
        Attempt.dimension, Attempt.started_at,
    ).where(Attempt.mode == "annotation")
    if annotator:
        query = query.where(Attempt.annotator_id == annotator)

    chains: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for attempt_id, annotator_id, task_id, dimension, _ in session.execute(
        query.order_by(Attempt.started_at, Attempt.attempt_id)
    ):
        chains[(annotator_id, task_id, dimension)].append(attempt_id)

    out: dict[str, tuple[int, int]] = {}
    for ids in chains.values():
        for index, attempt_id in enumerate(ids, start=1):
            out[attempt_id] = (index, len(ids))
    return defaultdict(lambda: (1, 1), out)


def _tickets(session: Session, annotator: str | None) -> dict[tuple[str, str], str]:
    """(标注者, 任务) → 标注者侧栏上看到的编号，如 `S1-5`。

    那是「第 1 个模态块的第 5 条」这样的位置标签：不含样本身份，
    **而且每个人的 S1-5 是不同样本**——队列各自打乱过。所以必须连
    标注者一起算，不能只按任务查。

    位置按该标注者队列里同模态任务的 `order_index` 先后数，
    与前端算块内序号是同一套规则；两边对不上的话，查出来的会是另一条。
    """
    query = select(Assignment.annotator_id, Assignment.task_id, Task.modality).join(
        Task, Task.task_id == Assignment.task_id
    )
    if annotator:
        query = query.where(Assignment.annotator_id == annotator)
    rows = session.execute(query.order_by(Assignment.order_index)).all()

    seen: Counter[tuple[str, str]] = Counter()
    out: dict[tuple[str, str], str] = {}
    for annotator_id, task_id, modality in rows:
        seen[(annotator_id, modality)] += 1
        block = MODALITIES.index(modality) + 1 if modality in MODALITIES else 0
        out[(annotator_id, task_id)] = f"S{block}-{seen[(annotator_id, modality)]}"
    return out


@router.delete("/annotators/{annotator_id}", dependencies=[Depends(require_admin)])
def delete_annotator(
    annotator_id: str, confirm: str, session: Session = Depends(get_session)
) -> dict:
    """删除标注者及其全部数据。**不可恢复。**

    `confirm` 必须与 `annotator_id` 一致：点错一行就删掉别人几十小时的
    标注，这道门槛挡的就是这个。UI 那边再加一次弹窗确认。

    删法与 `manage.py drop-annotator` 共用同一个函数——两处各写一套的话，
    迟早有一处漏删某张表，留下指向已删账号的孤儿行。
    """
    if confirm != annotator_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"确认参数与要删除的账号不一致（收到 {confirm!r}）。",
        )
    if session.get(Annotator, annotator_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到该标注者。")
    removed = purge_annotator(session, annotator_id)
    session.commit()
    return {"annotator_id": annotator_id, "removed": removed}





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
