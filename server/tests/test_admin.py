from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Assignment, Submission

ADMIN = {"Authorization": "Bearer admin-token"}
NOW = datetime.now(timezone.utc)


def test_admin_requires_a_token(client: TestClient):
    assert client.get("/api/admin/progress").status_code == 401


def test_wrong_admin_token_is_rejected(client: TestClient):
    response = client.get(
        "/api/admin/progress", headers={"Authorization": "Bearer nope"}
    )
    assert response.status_code == 401


def test_annotator_token_cannot_reach_admin(client: TestClient, auth):
    """标注者令牌绝不能看到别人的数据。"""
    assert client.get("/api/admin/progress", headers=auth).status_code == 401


def test_progress_counts_assignments_and_anchors(
    client: TestClient, session: Session, annotator, task, second_task
):
    session.add_all(
        [
            Assignment(
                annotator_id=annotator.annotator_id,
                task_id=task.task_id,
                phase="pilot",
                order_index=0,
                is_anchor=True,
            ),
            Assignment(
                annotator_id=annotator.annotator_id,
                task_id=second_task.task_id,
                phase="pilot",
                order_index=1,
            ),
        ]
    )
    session.commit()

    body = client.get("/api/admin/progress", headers=ADMIN).json()
    row = next(r for r in body["annotators"] if r["annotator_id"] == "A001")
    assert row["assigned"] == 2
    assert row["anchors"] == 1
    assert row["submitted"] == 0
    assert row["phase"] == "pilot"


def test_progress_counts_a_task_once_despite_multiple_revisions(
    client: TestClient, session: Session, annotator, task, attempt, second_attempt
):
    """同一任务提交两版仍算完成一个任务，否则进度虚高。"""
    session.add_all(
        [
            Submission(
                submission_id="s1",
                task_id=task.task_id,
                annotator_id=annotator.annotator_id,
                attempt_id=attempt.attempt_id,
                revision=1,
                submitted_at=NOW,
            ),
            Submission(
                submission_id="s2",
                task_id=task.task_id,
                annotator_id=annotator.annotator_id,
                attempt_id=second_attempt.attempt_id,
                revision=2,
                previous_submission_id="s1",
                submitted_at=NOW,
            ),
        ]
    )
    session.commit()

    body = client.get("/api/admin/progress", headers=ADMIN).json()
    row = next(r for r in body["annotators"] if r["annotator_id"] == "A001")
    assert row["submitted"] == 1


def test_progress_lists_annotators_with_nothing_assigned(
    client: TestClient, annotator
):
    """刚建好、还没分配的账号也要出现，否则看不出谁被漏掉了。"""
    body = client.get("/api/admin/progress", headers=ADMIN).json()
    assert [r["annotator_id"] for r in body["annotators"]] == ["A001"]
    assert body["annotators"][0]["assigned"] == 0


def test_single_annotator_export_matches_v1_shape(
    client: TestClient, annotator, attempt
):
    """带 ?annotator= 的导出要能被现有绘图脚本直接读。"""
    body = client.get("/api/admin/export?annotator=A001", headers=ADMIN).json()
    assert body["schema_version"] == 1
    assert body["annotator_id"] == "A001"
    assert "attempts" in body and "submissions" in body


def test_bundle_export_covers_everyone(
    client: TestClient, annotator, other_annotator
):
    body = client.get("/api/admin/export", headers=ADMIN).json()
    assert [a["annotator_id"] for a in body["annotators"]] == ["A001", "A002"]


def test_export_of_unknown_annotator_is_404(client: TestClient, annotator):
    assert (
        client.get("/api/admin/export?annotator=ghost", headers=ADMIN).status_code
        == 404
    )
