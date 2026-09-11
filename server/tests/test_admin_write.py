from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import hash_token
from app.models import Annotator, Assignment, AttemptFlag

ADMIN = {"Authorization": "Bearer admin-token"}


# --------------------------------------------------------------- 账号


def test_batch_create_returns_tokens_once(client: TestClient, session: Session):
    body = client.post(
        "/api/admin/annotators",
        headers=ADMIN,
        json={"count": 3, "phase": "pilot", "prefix": "P1", "base_url": "https://x/a"},
    ).json()

    assert [r["annotator_id"] for r in body["created"]] == ["P1-01", "P1-02", "P1-03"]
    assert all(r["url"].endswith(r["token"]) for r in body["created"])

    # 服务器只存哈希：明文既查不到也推不回去
    stored = session.scalars(select(Annotator.token_hash)).all()
    for row in body["created"]:
        assert row["token"] not in stored
        assert hash_token(row["token"]) in stored


def test_batch_create_skips_existing_ids(client: TestClient):
    """重跑不能给已有账号换一套令牌——那会把发出去的链接全部作废。"""
    payload = {"count": 2, "phase": "pilot", "prefix": "P1"}
    first = client.post("/api/admin/annotators", headers=ADMIN, json=payload).json()
    again = client.post(
        "/api/admin/annotators",
        headers=ADMIN,
        json={"count": 3, "phase": "pilot", "prefix": "P1"},
    ).json()

    assert [r["annotator_id"] for r in first["created"]] == ["P1-01", "P1-02"]
    assert again["skipped"] == ["P1-01", "P1-02"]
    assert [r["annotator_id"] for r in again["created"]] == ["P1-03"]


def test_create_rejects_unknown_phase(client: TestClient):
    response = client.post(
        "/api/admin/annotators",
        headers=ADMIN,
        json={"count": 1, "phase": "production", "prefix": "X"},
    )
    assert response.status_code == 400


def test_deactivating_an_annotator_blocks_their_token(
    client: TestClient, annotator, auth
):
    """停用要立刻生效，否则"撤销访问"只是个说法。"""
    assert client.get("/api/me", headers=auth).status_code == 200
    client.patch(
        "/api/admin/annotators/A001", headers=ADMIN, json={"active": False}
    )
    assert client.get("/api/me", headers=auth).status_code == 403


def test_write_endpoints_reject_annotator_tokens(client: TestClient, annotator, auth):
    assert (
        client.post(
            "/api/admin/annotators",
            headers=auth,
            json={"count": 1, "phase": "pilot", "prefix": "Z"},
        ).status_code
        == 401
    )


# --------------------------------------------------------------- 分配


def test_setting_a_queue_expands_samples_to_all_modalities(
    client: TestClient, session: Session, annotator, task, second_task
):
    """分配以样本为单位，落库时展开成该样本下的全部模态任务。"""
    body = client.put(
        "/api/admin/assignments/A001",
        headers=ADMIN,
        json={"phase": "pilot", "queue": [{"sample_id": "meld_dia11_utt9"}]},
    ).json()
    assert body["written"] == 2  # 夹具里该样本有两个任务
    rows = session.scalars(select(Assignment)).all()
    assert {r.task_id for r in rows} == {"EXAMPLE-001", "EXAMPLE-002"}


def test_queue_order_is_preserved_and_anchors_marked(
    client: TestClient, session: Session, annotator, task, second_task
):
    client.put(
        "/api/admin/assignments/A001",
        headers=ADMIN,
        json={
            "phase": "pilot",
            "queue": [{"sample_id": "meld_dia11_utt9", "is_anchor": True}],
        },
    )
    rows = session.scalars(select(Assignment)).all()
    assert all(r.order_index == 0 for r in rows)
    assert all(r.is_anchor for r in rows)


def test_setting_a_queue_replaces_rather_than_appends(
    client: TestClient, session: Session, annotator, task, second_task
):
    """半新半旧的队列比错误的队列更难排查，所以整体替换。"""
    for _ in range(2):
        client.put(
            "/api/admin/assignments/A001",
            headers=ADMIN,
            json={"phase": "pilot", "queue": [{"sample_id": "meld_dia11_utt9"}]},
        )
    assert len(session.scalars(select(Assignment)).all()) == 2


def test_unknown_samples_are_reported_not_silently_dropped(
    client: TestClient, annotator, task
):
    body = client.put(
        "/api/admin/assignments/A001",
        headers=ADMIN,
        json={"phase": "pilot", "queue": [{"sample_id": "nope"}]},
    ).json()
    assert body["missing_samples"] == ["nope"]
    assert body["written"] == 0


# --------------------------------------------------------------- 质量标记


def test_voiding_keeps_the_raw_attempt(
    client: TestClient, session: Session, annotator, task, attempt
):
    """作废是追加处置记录，不删数据——判断错了还要能翻案。"""
    client.post(
        "/api/admin/attempts/att-1/flags",
        headers=ADMIN,
        json={"flag": "void", "note": "说话人指错"},
    )
    assert session.get(type(attempt), "att-1") is not None
    flags = session.scalars(select(AttemptFlag)).all()
    assert [f.flag for f in flags] == ["void"]
    assert flags[0].note == "说话人指错"


def test_flag_history_accumulates(client: TestClient, session: Session, attempt):
    for flag in ("low_quality", "void", "ok"):
        client.post(
            f"/api/admin/attempts/att-1/flags", headers=ADMIN, json={"flag": flag}
        )
    assert len(session.scalars(select(AttemptFlag)).all()) == 3


def test_unknown_flag_is_rejected(client: TestClient, attempt):
    response = client.post(
        "/api/admin/attempts/att-1/flags", headers=ADMIN, json={"flag": "maybe"}
    )
    assert response.status_code == 400


def test_flagging_a_missing_attempt_is_404(client: TestClient, annotator):
    response = client.post(
        "/api/admin/attempts/ghost/flags", headers=ADMIN, json={"flag": "void"}
    )
    assert response.status_code == 404


def test_attempt_list_shows_the_latest_flag(client: TestClient, attempt):
    for flag in ("low_quality", "void"):
        client.post(
            "/api/admin/attempts/att-1/flags", headers=ADMIN, json={"flag": flag}
        )
    rows = client.get("/api/admin/attempts", headers=ADMIN).json()
    assert rows[0]["attempt_id"] == "att-1"
    assert rows[0]["flag"] == "void"
