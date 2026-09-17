"""完成判定与「取最新」。

V3 一个子任务要标效价与唤醒**两轮**，各是一条独立的提交链。由此带来两件
以前不存在的事：

* **完成 = 两个维度都交了。** 按提交条数或按 task_id 去重来数「完成多少」，
  会把只标了一半的算成标完——进度表看着漂亮，数据缺一半维度，
  而这件事要等到分析阶段才暴露。
* **重标产生多个版本，读取时只认最新的那版。** 旧版留着是为了查证
  「这个人重标过几次」，但拼曲线、算一致性时必须只取最新，
  否则同一个人对同一段素材会贡献两条互相矛盾的曲线。
"""

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import DIMENSIONS
from .models import Submission


def _by_chain(rows: list[Submission]) -> dict[tuple[str, str, str], Submission]:
    """(标注者, 子任务, 维度) → 版本号最大的那条提交。"""
    newest: dict[tuple[str, str, str], Submission] = {}
    for row in rows:
        key = (row.annotator_id, row.task_id, row.dimension)
        current = newest.get(key)
        if current is None or row.revision > current.revision:
            newest[key] = row
    return newest


def latest_submissions(
    session: Session, annotator_id: str | None = None
) -> list[Submission]:
    """每条链只留最新一版。不带 `annotator_id` 时返回全部标注者的。"""
    query = select(Submission)
    if annotator_id is not None:
        query = query.where(Submission.annotator_id == annotator_id)
    return list(_by_chain(list(session.scalars(query))).values())


def superseded_ids(session: Session, annotator_id: str | None = None) -> set[str]:
    """被更新版本顶替掉的提交编号。

    导出时给它们打上标记，分析脚本就能一眼跳过，而不必自己重算版本链。
    """
    query = select(Submission)
    if annotator_id is not None:
        query = query.where(Submission.annotator_id == annotator_id)
    rows = list(session.scalars(query))
    keep = {row.submission_id for row in _by_chain(rows).values()}
    return {row.submission_id for row in rows} - keep


def completed_tasks(session: Session, annotator_id: str) -> set[str]:
    """这位标注者**两个维度都交齐**的子任务。

    只交一个维度不算，同一维度重标三遍也不算——数条数会在这里出错。
    """
    seen: dict[str, set[str]] = defaultdict(set)
    for row in session.scalars(
        select(Submission).where(Submission.annotator_id == annotator_id)
    ):
        seen[row.task_id].add(row.dimension)
    wanted = set(DIMENSIONS)
    return {task_id for task_id, dims in seen.items() if dims >= wanted}


def completed_counts(session: Session) -> dict[str, int]:
    """各标注者标完的子任务数，供进度总览。"""
    seen: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in session.scalars(select(Submission)):
        seen[row.annotator_id][row.task_id].add(row.dimension)
    wanted = set(DIMENSIONS)
    return {
        annotator: sum(1 for dims in tasks.values() if dims >= wanted)
        for annotator, tasks in seen.items()
    }
