"""删除标注者：账号与全部标注数据一起清掉，不可恢复。

管理端要能自己收拾场面——试标账号、建错的账号、退出的人，不该为了删一个
账号去 ssh 上服务器跑命令。但这是**不可逆**的：轮次、采样、提交全没，
所以接口只认明确的确认参数，UI 那边再加一道弹窗。
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import (
    Annotator, Assignment, Attempt, AttemptFlag, SampleChunk, Submission,
)

ADMIN = {"Authorization": "Bearer admin-token"}
NOW = datetime(2026, 9, 17, tzinfo=timezone.utc)


@pytest.fixture
def with_data(session: Session, annotator: Annotator, task, attempt, assigned):
    session.add(SampleChunk(attempt_id=attempt.attempt_id, chunk_index=0,
                            samples=[{"sample_index": 0, "media_time": 0.0,
                                      "value": 0.1}]))
    session.add(Submission(submission_id="s1", task_id=task.task_id,
                           annotator_id=annotator.annotator_id,
                           attempt_id=attempt.attempt_id, dimension="valence",
                           revision=1, submitted_at=NOW))
    session.add(AttemptFlag(attempt_id=attempt.attempt_id, flag="void",
                            note="", flagged_at=NOW))
    session.commit()
    return annotator.annotator_id


def test_delete_removes_the_account_and_everything_it_produced(
    client: TestClient, session: Session, with_data: str
):
    response = client.delete(
        f"/api/admin/annotators/{with_data}?confirm={with_data}", headers=ADMIN
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["annotator_id"] == with_data
    assert body["removed"]["attempts"] == 1
    assert body["removed"]["submissions"] == 1
    assert body["removed"]["sample_chunks"] == 1

    # 测试与接口共用同一个 session，删除发生在它的 identity map 之外
    session.expire_all()
    assert session.get(Annotator, with_data) is None
    assert session.query(Attempt).count() == 0
    assert session.query(Submission).count() == 0
    assert session.query(SampleChunk).count() == 0
    assert session.query(Assignment).count() == 0
    assert session.query(AttemptFlag).count() == 0


def test_delete_needs_the_id_typed_back(client: TestClient, with_data: str):
    """确认参数必须与要删的账号一致——点错行就不该删掉别人的数据。"""
    response = client.delete(
        f"/api/admin/annotators/{with_data}?confirm=别的账号", headers=ADMIN
    )
    assert response.status_code == 400
    assert "确认" in response.json()["detail"]


def test_delete_without_confirm_is_refused(client: TestClient, with_data: str):
    assert client.delete(
        f"/api/admin/annotators/{with_data}", headers=ADMIN
    ).status_code == 422


def test_deleting_an_unknown_account_is_404(client: TestClient, with_data: str):
    assert client.delete(
        "/api/admin/annotators/NOBODY?confirm=NOBODY", headers=ADMIN
    ).status_code == 404


def test_delete_is_admin_only(client: TestClient, with_data: str):
    assert client.delete(
        f"/api/admin/annotators/{with_data}?confirm={with_data}"
    ).status_code == 401


def test_other_accounts_are_untouched(
    client: TestClient, session: Session, with_data: str, other_annotator
):
    client.delete(
        f"/api/admin/annotators/{with_data}?confirm={with_data}", headers=ADMIN
    )
    session.expire_all()
    assert session.get(Annotator, other_annotator.annotator_id) is not None
