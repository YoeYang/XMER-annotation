"""效价与唤醒必须各记各的账。

V3 的一个子任务（样本 × 模态）要标两个维度，各是一条独立的 attempt、
一次独立的提交。Yoe 定的口径：**两个维度像纯视觉、纯语音那样彻底隔离**，
一个样本一个标注者产出 5 模态 × 2 维度 = 10 份独立记录。

这批测试钉住三件事：版本链按维度各走各的、两维齐全才算完成、
断网重传不会把两个维度搅在一起。
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Attempt, Submission

NOW = datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc).isoformat()


def body(dimension: str, **kw) -> dict:
    out = {
        "task_id": "EXAMPLE-001",
        "media_id": "example-face",
        "modality": "face",
        "mode": "annotation",
        "dimension": dimension,
        "familiarization_plays": 2,
        "status": "completed",
        "task_snapshot": {"task_id": "EXAMPLE-001"},
        "events": [],
        "sample_rate_hz": 10,
        "started_at": NOW,
        "completed_at": NOW,
    }
    out.update(kw)
    return out


def record(client, assigned, attempt_id: str, dimension: str):
    """跑完一个维度的一轮标注：建轮次、写一块采样。"""
    client.put(f"/api/attempts/{attempt_id}", json=body(dimension), headers=assigned)
    client.put(
        f"/api/attempts/{attempt_id}/chunks/0",
        json={"samples": [{"sample_index": 0, "media_time": 0.0, "value": 0.1}]},
        headers=assigned,
    )


def submit(client, assigned, attempt_id: str, submission_id: str):
    return client.post(
        f"/api/attempts/{attempt_id}/submit",
        json={"submission_id": submission_id},
        headers=assigned,
    )


# --------------------------------------------------- 两个维度各走各的版本链


def test_the_two_dimensions_are_separate_chains(client: TestClient, assigned):
    """先交效价再交唤醒，唤醒**不是**效价的修订版。

    没有这条，第二个维度会被记成 revision 2 并指回第一个维度——
    系统以为标注者把效价改了，其实他标的是唤醒。
    """
    record(client, assigned, "att-1", "valence")
    record(client, assigned, "att-2", "arousal")

    first = submit(client, assigned, "att-1", "sub-v1").json()
    second = submit(client, assigned, "att-2", "sub-a1").json()

    assert first["dimension"] == "valence"
    assert second["dimension"] == "arousal"
    assert second["revision"] == 1, "唤醒是自己那条链的第一版"
    assert second["previous_submission_id"] is None
    assert second["updated_at"] is None


def test_redoing_one_dimension_chains_within_that_dimension(
    client: TestClient, assigned
):
    """同一维度重标才形成 revision 2，且指回同维度的上一版。"""
    record(client, assigned, "att-1", "valence")
    record(client, assigned, "att-2", "arousal")
    record(client, assigned, "att-3", "valence")

    submit(client, assigned, "att-1", "sub-v1")
    submit(client, assigned, "att-2", "sub-a1")
    again = submit(client, assigned, "att-3", "sub-v2").json()

    assert again["dimension"] == "valence"
    assert again["revision"] == 2
    assert again["previous_submission_id"] == "sub-v1", "要指回效价的上一版，不是唤醒"


def test_replay_of_one_dimension_does_not_disturb_the_other(
    client: TestClient, session: Session, assigned
):
    """断网重传同一 submission_id 返回原记录，另一维度不受影响。"""
    record(client, assigned, "att-1", "valence")
    record(client, assigned, "att-2", "arousal")
    submit(client, assigned, "att-1", "sub-v1")
    submit(client, assigned, "att-2", "sub-a1")

    replay = submit(client, assigned, "att-1", "sub-v1").json()

    assert replay["dimension"] == "valence"
    assert replay["revision"] == 1
    assert session.query(Submission).count() == 2


def test_submission_carries_the_dimension_of_its_attempt(
    client: TestClient, session: Session, assigned
):
    """维度取自轮次本身，不由客户端另行声明——两处各报一次就会对不上。"""
    record(client, assigned, "att-2", "arousal")
    submit(client, assigned, "att-2", "sub-a1")

    row = session.get(Submission, "sub-a1")
    assert row.dimension == session.get(Attempt, "att-2").dimension
