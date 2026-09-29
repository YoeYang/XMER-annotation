"""训练与正式同一个账号（2026-09-29 版）。

正式标注者名下同时挂 training 与 main 两批分配：训练两维全部交齐之前只发训练，
交齐后服务端写 `trained_at`，自动解锁正式任务（Yoe 定：不要人工放行）。
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.auth import hash_token
from app.models import Annotator, Assignment, Attempt, Submission, Task

NOW = datetime(2026, 9, 30, 9, 0, tzinfo=timezone.utc)
HEADERS = {"Authorization": "Bearer token-p1"}


def make_task(session, task_id, modality):
    session.add(Task(task_id=task_id, media_id=f"m-{task_id}", source_id=f"src-{task_id}",
                     title=task_id, modality=modality, src=f"/m/{task_id}", duration=3.0))


def assign(session, annotator_id, task_id, phase, order_index):
    session.flush()  # 没有 ORM 关系，不先落账号与任务，外键会先于它们插入
    session.add(Assignment(annotator_id=annotator_id, task_id=task_id,
                           phase=phase, order_index=order_index))


def finish(session, annotator_id, task_id, dimensions=("valence", "arousal")):
    """直接落两维提交，等价于标注者交齐这个子任务。"""
    for dimension in dimensions:
        attempt_id = f"{annotator_id}-{task_id}-{dimension}"
        session.add(Attempt(
            attempt_id=attempt_id, task_id=task_id, annotator_id=annotator_id,
            media_id=f"m-{task_id}", modality="face", mode="annotation",
            dimension=dimension, status="completed", task_snapshot={}, events=[],
            sample_rate_hz=10, started_at=NOW,
        ))
        session.add(Submission(
            submission_id=f"sub-{attempt_id}", task_id=task_id, annotator_id=annotator_id,
            attempt_id=attempt_id, dimension=dimension, revision=1, submitted_at=NOW,
        ))
    session.commit()


@pytest.fixture
def stage1(session: Session) -> Annotator:
    """P1-ZH-01：两条训练（face、audio）+ 两条正式。"""
    row = Annotator(annotator_id="P1-ZH-01", token_hash=hash_token("token-p1"),
                    phase="main", language="zh")
    session.add(row)
    for task_id, modality in [("TR-face", "face"), ("TR-audio", "audio"),
                              ("MAIN-1", "face"), ("MAIN-2", "text")]:
        make_task(session, task_id, modality)
    assign(session, "P1-ZH-01", "TR-face", "training", 0)
    assign(session, "P1-ZH-01", "TR-audio", "training", 1)
    assign(session, "P1-ZH-01", "MAIN-1", "main", 0)
    assign(session, "P1-ZH-01", "MAIN-2", "main", 1)
    session.commit()
    return row


def attempt_body(task_id, modality="face"):
    return {
        "task_id": task_id, "media_id": f"m-{task_id}", "modality": modality,
        "mode": "annotation", "dimension": "valence", "status": "recording",
        "task_snapshot": {"task_id": task_id}, "sample_rate_hz": 10,
        "started_at": NOW.isoformat(),
    }


def task_ids(client):
    body = client.get("/api/me", headers=HEADERS).json()
    return body["phase"], [t["task_id"] for t in body["tasks"]]


# ----------------------------------------------------- 训练在前


def test_a_new_account_sees_only_its_training(client, stage1):
    assert task_ids(client) == ("training", ["TR-face", "TR-audio"])


def test_main_tasks_are_locked_during_training(client, stage1):
    """访问隔离跟着当前阶段走：训练没交齐，正式任务碰都碰不到。"""
    response = client.put("/api/attempts/a1", json=attempt_body("MAIN-1"), headers=HEADERS)
    assert response.status_code == 404
    response = client.put("/api/attempts/a2", json=attempt_body("TR-face"), headers=HEADERS)
    assert response.status_code == 200


def test_half_a_subtask_does_not_unlock(client, session, stage1):
    """只交一个维度不算完成，差一条都不解锁。"""
    finish(session, "P1-ZH-01", "TR-face")
    finish(session, "P1-ZH-01", "TR-audio", dimensions=("valence",))
    assert task_ids(client)[0] == "training"
    assert session.get(Annotator, "P1-ZH-01").trained_at is None


# ----------------------------------------------------- 自动解锁


def test_finishing_training_unlocks_main_automatically(client, session, stage1):
    finish(session, "P1-ZH-01", "TR-face")
    finish(session, "P1-ZH-01", "TR-audio")
    assert task_ids(client) == ("main", ["MAIN-1", "MAIN-2"])
    session.expire_all()  # 应用用自己的会话写的，测试会话里那份是旧的
    assert session.get(Annotator, "P1-ZH-01").trained_at is not None


def test_after_unlock_training_tasks_are_closed(client, session, stage1):
    finish(session, "P1-ZH-01", "TR-face")
    finish(session, "P1-ZH-01", "TR-audio")
    task_ids(client)
    response = client.put("/api/attempts/a3", json=attempt_body("TR-face"), headers=HEADERS)
    assert response.status_code == 404
    response = client.put("/api/attempts/a4", json=attempt_body("MAIN-1"), headers=HEADERS)
    assert response.status_code == 200


def test_the_last_debrief_is_still_readable_after_unlock(client, session, stage1):
    """做完最后一段训练时账号已经解锁，那一段的复盘照样要能看。"""
    finish(session, "P1-ZH-01", "TR-face")
    finish(session, "P1-ZH-01", "TR-audio")
    task_ids(client)
    assert client.get("/api/training/debrief/audio", headers=HEADERS).status_code == 200


def test_main_tasks_never_get_a_debrief(client, session, stage1):
    """正式任务永远拿不到参考曲线：text 只在正式分配里，没有训练分配。"""
    finish(session, "P1-ZH-01", "TR-face")
    finish(session, "P1-ZH-01", "TR-audio")
    task_ids(client)
    assert client.get("/api/training/debrief/text", headers=HEADERS).status_code == 404


# ----------------------------------------------------- 边界


def test_an_account_without_training_goes_straight_to_main(client, session):
    session.add(Annotator(annotator_id="P1-EN-07", token_hash=hash_token("token-p1"),
                          phase="main", language="en"))
    make_task(session, "MAIN-1", "face")
    assign(session, "P1-EN-07", "MAIN-1", "main", 0)
    session.commit()
    assert task_ids(client) == ("main", ["MAIN-1"])


def test_preview_accounts_never_unlock(client, session):
    """公用预览号（phase=training）做完也停在训练，不会冒出空的正式队列。"""
    session.add(Annotator(annotator_id="TRZH-01", token_hash=hash_token("token-p1"),
                          phase="training", language="zh"))
    make_task(session, "TR-face", "face")
    assign(session, "TRZH-01", "TR-face", "training", 0)
    session.commit()
    finish(session, "TRZH-01", "TR-face")
    assert task_ids(client) == ("training", ["TR-face"])
    assert session.get(Annotator, "TRZH-01").trained_at is None
