"""轮次处置要看得出这是第几版重标。

同一个人对同一条样本的同一个维度可以标好几遍——重标形成新轮次、新提交，
旧的都留着。处置时必须分得清哪版是最新、哪些是被顶替的：
把当前有效的那版作废掉，等于把这条样本的数据废了；
而想废掉的往往恰恰是早先那几版。
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Attempt, Submission

ADMIN = {"Authorization": "Bearer admin-token"}
NOW = datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)


def add_round(session, annotator, task_id, dimension, n, *, submitted=True):
    attempt_id = f"{dimension[:3]}-{n}"
    session.add(
        Attempt(
            attempt_id=attempt_id, task_id=task_id, annotator_id=annotator,
            media_id="m", modality="face", mode="annotation", dimension=dimension,
            status="completed", task_snapshot={}, events=[], sample_rate_hz=10,
            started_at=NOW + timedelta(minutes=n),
            server_received_at=NOW + timedelta(minutes=n),
        )
    )
    if submitted:
        session.add(
            Submission(
                submission_id=f"sub-{attempt_id}", task_id=task_id,
                annotator_id=annotator, attempt_id=attempt_id,
                dimension=dimension, revision=n,
                submitted_at=NOW + timedelta(minutes=n),
            )
        )
    session.commit()


def test_rounds_are_numbered_per_dimension(
    client: TestClient, session: Session, annotator, task, assigned
):
    """效价标三遍、唤醒标一遍——两个维度各自从第 1 版数起。"""
    for n in (1, 2, 3):
        add_round(session, annotator.annotator_id, task.task_id, "valence", n)
    add_round(session, annotator.annotator_id, task.task_id, "arousal", 4)

    rows = client.get("/api/admin/attempts", headers=ADMIN).json()
    by_id = {r["attempt_id"]: r for r in rows}
    assert [by_id[f"val-{n}"]["attempt_no"] for n in (1, 2, 3)] == [1, 2, 3]
    assert by_id["aro-4"]["attempt_no"] == 1, "唤醒是它自己那条链的第 1 版"


def test_only_the_last_round_is_current(
    client: TestClient, session: Session, annotator, task, assigned
):
    """标三遍只有最后一遍算数，处置时别把它废了。"""
    for n in (1, 2, 3):
        add_round(session, annotator.annotator_id, task.task_id, "valence", n)

    rows = client.get("/api/admin/attempts", headers=ADMIN).json()
    current = [r["attempt_id"] for r in rows if r["is_current"]]
    assert current == ["val-3"]


def test_unsubmitted_round_still_gets_a_number(
    client: TestClient, session: Session, annotator, task, assigned
):
    """标到一半没提交的也要编号，否则表上看不出它夹在哪两版之间。"""
    add_round(session, annotator.annotator_id, task.task_id, "valence", 1)
    add_round(session, annotator.annotator_id, task.task_id, "valence", 2,
              submitted=False)

    rows = {r["attempt_id"]: r for r in
            client.get("/api/admin/attempts", headers=ADMIN).json()}
    assert rows["val-2"]["attempt_no"] == 2
    assert rows["val-2"]["revision"] is None, "没提交就没有提交版本号"
    assert rows["val-1"]["revision"] == 1


def test_rounds_are_counted_per_annotator(
    client: TestClient, session: Session, annotator, other_annotator, task,
    assigned, other_assigned,
):
    """别人标过多少遍与我无关——两个人各自从第 1 版数起。"""
    add_round(session, annotator.annotator_id, task.task_id, "valence", 1)
    add_round(session, annotator.annotator_id, task.task_id, "valence", 2)
    add_round(session, other_annotator.annotator_id, task.task_id, "valence", 3)

    rows = {r["attempt_id"]: r for r in
            client.get("/api/admin/attempts", headers=ADMIN).json()}
    assert rows["val-3"]["attempt_no"] == 1
    assert rows["val-3"]["annotator_id"] == other_annotator.annotator_id
