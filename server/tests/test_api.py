from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Assignment, Attempt, Submission

NOW = datetime.now(timezone.utc).isoformat()


def attempt_body(task_id: str = "EXAMPLE-001", **overrides) -> dict:
    body = {
        "task_id": task_id,
        "media_id": "example-face",
        "modality": "face",
        "mode": "annotation",
        "dimension": "valence",
        "familiarization_plays": 2,
        "status": "recording",
        "task_snapshot": {"task_id": task_id},
        "events": [],
        "sample_rate_hz": 10,
        "started_at": NOW,
        "completed_at": None,
    }
    body.update(overrides)
    return body


def samples(*indices: int) -> list[dict]:
    return [
        {"sample_index": i, "media_time": i * 0.1, "value": 0.1}
        for i in indices
    ]


# --------------------------------------------------------------- 身份与隔离


def test_missing_token_is_rejected(client: TestClient):
    assert client.get("/api/me").status_code == 401


def test_unknown_token_is_rejected(client: TestClient):
    response = client.get("/api/me", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


def test_deactivated_annotator_is_blocked(
    client: TestClient, session: Session, annotator, auth
):
    annotator.active = False
    session.commit()
    assert client.get("/api/me", headers=auth).status_code == 403


def test_me_lists_assigned_tasks_in_queue_order(
    client: TestClient, session: Session, annotator, task, second_task, auth
):
    session.add_all(
        [
            Assignment(
                annotator_id=annotator.annotator_id,
                task_id=second_task.task_id,
                phase="pilot",
                order_index=0,
            ),
            Assignment(
                annotator_id=annotator.annotator_id,
                task_id=task.task_id,
                phase="pilot",
                order_index=1,
            ),
        ]
    )
    session.commit()

    body = client.get("/api/me", headers=auth).json()
    assert [t["task_id"] for t in body["tasks"]] == ["EXAMPLE-002", "EXAMPLE-001"]
    assert body["tasks"][1]["speaker_name"] == "Phoebe"


def test_me_never_reveals_anchor_status(
    client: TestClient, session: Session, annotator, task, auth
):
    """标注者必须无从分辨哪些是锚点，否则锚点数据失去质控意义。"""
    session.add(
        Assignment(
            annotator_id=annotator.annotator_id,
            task_id=task.task_id,
            phase="pilot",
            order_index=0,
            is_anchor=True,
        )
    )
    session.commit()

    body = client.get("/api/me", headers=auth).json()
    assert "is_anchor" not in body["tasks"][0]
    assert "is_anchor" not in client.get("/api/me", headers=auth).text


def test_me_hides_other_phases(
    client: TestClient, session: Session, annotator, task, auth
):
    """pilot 标注者看不到分配在 main 阶段的同一样本。"""
    session.add(
        Assignment(
            annotator_id=annotator.annotator_id,
            task_id=task.task_id,
            phase="main",
            order_index=0,
        )
    )
    session.commit()
    assert client.get("/api/me", headers=auth).json()["tasks"] == []


def test_cannot_open_attempt_on_unassigned_task(client: TestClient, task, auth):
    response = client.put("/api/attempts/att-x", json=attempt_body(), headers=auth)
    assert response.status_code == 404


def test_cannot_touch_another_annotators_attempt(
    client: TestClient, session: Session, assigned, other_auth
):
    client.put("/api/attempts/att-1", json=attempt_body(), headers=assigned)
    response = client.put(
        "/api/attempts/att-1/chunks/0", json={"samples": samples(0)}, headers=other_auth
    )
    assert response.status_code == 404


# --------------------------------------------------------------- 幂等写入


def test_attempt_put_is_idempotent(client: TestClient, session: Session, assigned):
    for _ in range(3):
        response = client.put(
            "/api/attempts/att-1", json=attempt_body(), headers=assigned
        )
        assert response.status_code == 200
    assert session.query(Attempt).count() == 1


def test_attempt_annotator_comes_from_token_not_body(client: TestClient, assigned):
    """客户端无法冒充他人：annotator_id 由令牌决定，请求体里写什么都没用。"""
    body = attempt_body()
    body["annotator_id"] = "A999"
    response = client.put("/api/attempts/att-1", json=body, headers=assigned)
    assert response.json()["annotator_id"] == "A001"


def test_chunk_replay_is_ignored_not_duplicated(client: TestClient, assigned):
    client.put("/api/attempts/att-1", json=attempt_body(), headers=assigned)

    first = client.put(
        "/api/attempts/att-1/chunks/0", json={"samples": samples(0, 1)}, headers=assigned
    ).json()
    replay = client.put(
        "/api/attempts/att-1/chunks/0", json={"samples": samples(0, 1)}, headers=assigned
    ).json()

    assert first["stored"] is True
    assert replay["stored"] is False
    assert replay["sample_count"] == 2


def test_chunks_arriving_out_of_order_reassemble(client: TestClient, assigned):
    client.put("/api/attempts/att-1", json=attempt_body(), headers=assigned)
    for index in (2, 0, 1):
        client.put(
            f"/api/attempts/att-1/chunks/{index}",
            json={"samples": samples(index)},
            headers=assigned,
        )

    export = client.get("/api/export", headers=assigned).json()
    order = [s["sample_index"] for s in export["attempts"][0]["samples"]]
    assert order == [0, 1, 2]


def test_chunk_write_recomputes_progress(client: TestClient, assigned):
    """进度以库中实际内容为准，元数据 PUT 丢失也能自愈。"""
    client.put("/api/attempts/att-1", json=attempt_body(), headers=assigned)
    client.put(
        "/api/attempts/att-1/chunks/0", json={"samples": samples(0, 1)}, headers=assigned
    )
    body = client.put(
        "/api/attempts/att-1/chunks/1", json={"samples": samples(2)}, headers=assigned
    ).json()

    assert body["sample_count"] == 3
    listed = client.get("/api/attempts", headers=assigned).json()[0]
    assert listed["sample_count"] == 3
    assert listed["last_media_time"] == pytest.approx(0.2)


def test_negative_chunk_index_is_rejected(client: TestClient, assigned):
    client.put("/api/attempts/att-1", json=attempt_body(), headers=assigned)
    response = client.put(
        "/api/attempts/att-1/chunks/-1", json={"samples": []}, headers=assigned
    )
    assert response.status_code == 400


# --------------------------------------------------------------- 提交与版本链


def complete_attempt(client: TestClient, assigned, attempt_id="att-1"):
    client.put(
        f"/api/attempts/{attempt_id}",
        json=attempt_body(status="completed", completed_at=NOW),
        headers=assigned,
    )
    client.put(
        f"/api/attempts/{attempt_id}/chunks/0",
        json={"samples": samples(0)},
        headers=assigned,
    )


def test_submit_creates_revision_one(client: TestClient, assigned):
    complete_attempt(client, assigned)
    body = client.post(
        "/api/attempts/att-1/submit", json={"submission_id": "sub-1"}, headers=assigned
    ).json()
    assert body["revision"] == 1
    assert body["previous_submission_id"] is None
    assert body["updated_at"] is None


def test_submit_replay_returns_same_record(
    client: TestClient, session: Session, assigned
):
    """断网重试会重发同一 submission_id，不能变成第二个版本。"""
    complete_attempt(client, assigned)
    first = client.post(
        "/api/attempts/att-1/submit", json={"submission_id": "sub-1"}, headers=assigned
    ).json()
    replay = client.post(
        "/api/attempts/att-1/submit", json={"submission_id": "sub-1"}, headers=assigned
    ).json()

    assert replay == first
    assert session.query(Submission).count() == 1


def test_update_chains_to_previous_revision(client: TestClient, assigned):
    complete_attempt(client, assigned)
    client.post(
        "/api/attempts/att-1/submit", json={"submission_id": "sub-1"}, headers=assigned
    )
    complete_attempt(client, assigned, attempt_id="att-2")
    second = client.post(
        "/api/attempts/att-2/submit", json={"submission_id": "sub-2"}, headers=assigned
    ).json()

    assert second["revision"] == 2
    assert second["previous_submission_id"] == "sub-1"
    assert second["updated_at"] is not None


def test_preview_attempt_cannot_be_submitted(client: TestClient, assigned):
    client.put(
        "/api/attempts/att-1",
        json=attempt_body(mode="preview", status="completed", completed_at=NOW),
        headers=assigned,
    )
    response = client.post(
        "/api/attempts/att-1/submit", json={"submission_id": "sub-1"}, headers=assigned
    )
    assert response.status_code == 409


def test_unfinished_attempt_cannot_be_submitted(client: TestClient, assigned):
    client.put("/api/attempts/att-1", json=attempt_body(), headers=assigned)
    response = client.post(
        "/api/attempts/att-1/submit", json={"submission_id": "sub-1"}, headers=assigned
    )
    assert response.status_code == 409


# --------------------------------------------------------------- 导出


def test_export_matches_v1_shape(client: TestClient, assigned):
    complete_attempt(client, assigned)
    client.post(
        "/api/attempts/att-1/submit", json={"submission_id": "sub-1"}, headers=assigned
    )

    body = client.get("/api/export", headers=assigned).json()
    assert body["schema_version"] == 1
    assert body["storage"] == "cloud"
    assert body["annotator_id"] == "A001"
    assert body["unsaved_attempt_ids"] == []

    attempt = body["attempts"][0]
    # 分析脚本按这些字段读数据，缺一不可
    for field in ("attempt_id", "modality", "samples", "events", "calibration"):
        assert field in attempt
    assert body["submissions"][0]["submission_id"] == "sub-1"


def test_export_is_scoped_to_the_caller(
    client: TestClient, assigned, other_auth, other_assigned
):
    complete_attempt(client, assigned)
    assert client.get("/api/export", headers=other_auth).json()["attempts"] == []


def test_timestamps_always_carry_timezone(client: TestClient, assigned):
    """回归：从库里读回的 naive datetime 曾让重放响应少了时区后缀。

    接口对外不能出现无时区时间戳，否则客户端只能靠猜是本地时间还是 UTC。
    """
    complete_attempt(client, assigned)
    client.post(
        "/api/attempts/att-1/submit", json={"submission_id": "sub-1"}, headers=assigned
    )

    listed = client.get("/api/attempts", headers=assigned).json()[0]
    submission = client.get("/api/submissions", headers=assigned).json()[0]
    export = client.get("/api/export", headers=assigned).json()

    for value in (
        listed["started_at"],
        listed["completed_at"],
        submission["submitted_at"],
        export["exported_at"],
        export["attempts"][0]["started_at"],
        export["submissions"][0]["submitted_at"],
    ):
        assert value.endswith("+00:00"), value


def test_attempt_cannot_be_submitted_twice_under_new_id(
    client: TestClient, session: Session, assigned
):
    """换个 submission_id 重发同一轮次，不能凭空生成 revision 2。

    重标的正当路径是另开一个轮次再提交；本地 IndexedDB 用唯一索引守住了
    「一轮次一提交」，服务端必须守住同一条。
    """
    complete_attempt(client, assigned)
    first = client.post(
        "/api/attempts/att-1/submit", json={"submission_id": "sub-1"}, headers=assigned
    ).json()
    again = client.post(
        "/api/attempts/att-1/submit", json={"submission_id": "sub-other"}, headers=assigned
    ).json()

    assert again["submission_id"] == first["submission_id"]
    assert again["revision"] == 1
    assert session.query(Submission).count() == 1


def test_attempt_out_carries_every_field_the_client_restores(
    client: TestClient, assigned
):
    """跨设备恢复要用这些字段还原 Attempt，缺一个前端就拼不回来。"""
    client.put("/api/attempts/att-1", json=attempt_body(), headers=assigned)
    body = client.get("/api/attempts", headers=assigned).json()[0]

    for field in (
        "schema_version",
        "attempt_id",
        "task_id",
        "annotator_id",
        "media_id",
        "modality",
        "mode",
        "status",
        "task_snapshot",
        "sample_rate_hz",
        "started_at",
        "completed_at",
        "sample_count",
        "last_media_time",
        "events",
        "calibration",
    ):
        assert field in body, field


def test_queue_puts_full_video_after_the_single_modalities(
    client: TestClient, session: Session, annotator, auth
):
    """回归：同一样本的四个任务 order_index 相同，次级排序若不定义，
    服务器可能把完整视频排在最前——而先看完整视频正是要避免的污染。
    侧栏只在显示时排序，默认选中的任务和「下一个样本」都跟服务器顺序走。

    完整视频**先**插入，使"按插入顺序返回"会给出错误答案。
    """
    from app.models import Task

    for task_id, modality in (
        ("EX-AV", "audiovisual"),
        ("EX-TX", "text"),
        ("EX-AU", "audio"),
        ("EX-BD", "body"),
        ("EX-FC", "face"),
    ):
        session.add(
            Task(
                task_id=task_id,
                media_id="m-" + task_id,
                source_id="meld_dia11_utt9",
                title=task_id,
                modality=modality,
                src="/media/x",
                duration=6.715,
            )
        )
        session.flush()
        session.add(
            Assignment(
                annotator_id=annotator.annotator_id,
                task_id=task_id,
                phase="pilot",
                order_index=0,
            )
        )
    session.commit()

    order = [t["modality"] for t in client.get("/api/me", headers=auth).json()["tasks"]]
    assert order == ["face", "body", "audio", "text", "audiovisual"]


# --------------------------------------------------------------- 读回采样点


def test_can_read_back_own_samples_in_order(
    client: TestClient, session: Session, assigned
):
    """罗盘下方要画四个模态的曲线，得能按轮次把采样点读回来。"""
    client.put("/api/attempts/att-1", json=attempt_body(), headers=assigned)
    # 故意乱序写入：读回来必须按 sample_index 排好
    client.put(
        "/api/attempts/att-1/chunks/1", json={"samples": samples(10, 11)}, headers=assigned
    )
    client.put(
        "/api/attempts/att-1/chunks/0", json={"samples": samples(0, 1)}, headers=assigned
    )

    response = client.get("/api/attempts/att-1/samples", headers=assigned)
    assert response.status_code == 200
    assert [s["sample_index"] for s in response.json()] == [0, 1, 10, 11]
    assert response.json()[0]["value"] == 0.1


def test_cannot_read_another_annotators_samples(
    client: TestClient, session: Session, assigned, other_auth
):
    client.put("/api/attempts/att-1", json=attempt_body(), headers=assigned)
    client.put(
        "/api/attempts/att-1/chunks/0", json={"samples": samples(0)}, headers=assigned
    )
    assert client.get("/api/attempts/att-1/samples", headers=other_auth).status_code == 404
    assert client.get("/api/attempts/nope/samples", headers=assigned).status_code == 404


# --------------------------------------------------- V3：order_index 与维度


def test_me_serves_order_index_for_block_numbering(
    client, session, annotator, auth, task, second_task
):
    """前端要按模态分块算「面部 3/20」这种块内序号，靠的就是 order_index。

    它挂在 assignments 上而不是 tasks 上——同一个任务分给不同的人，
    队列位置本来就不同，所以必须连着分配记录一起取。
    """
    from app.models import Assignment

    for t, idx in ((task, 7), (second_task, 3)):
        session.add(
            Assignment(
                annotator_id=annotator.annotator_id,
                task_id=t.task_id,
                phase=annotator.phase,
                order_index=idx,
            )
        )
    session.commit()

    tasks = client.get("/api/me", headers=auth).json()["tasks"]
    got = {t["task_id"]: t["order_index"] for t in tasks}
    assert got == {task.task_id: 7, second_task.task_id: 3}
    # 队列顺序也按它排
    assert [t["task_id"] for t in tasks] == [second_task.task_id, task.task_id]


def test_attempt_round_trips_dimension_and_familiarization(client, assigned):
    """维度与熟悉页播放次数要原样存下并读回——前者决定这轮标的是什么，
    后者是质检信号（只播 0.3 遍就上手的人，质量要单独看）。"""
    body = attempt_body(dimension="arousal", familiarization_plays=5)
    response = client.put("/api/attempts/att-dim", json=body, headers=assigned)
    assert response.status_code == 200
    assert response.json()["dimension"] == "arousal"
    assert response.json()["familiarization_plays"] == 5


def test_attempt_rejects_unknown_dimension(client, assigned):
    response = client.put(
        "/api/attempts/att-bad", json=attempt_body(dimension="both"), headers=assigned
    )
    assert response.status_code == 422


def test_familiarization_plays_accepts_a_fraction(client: TestClient, assigned):
    """熟悉页播到一半就上手，记的是 1.4 遍而不是 1 遍。

    前端算的是「播放圈数 + 当前这遍的进度」，本来就是小数——
    `models.py` 的注释自己写着「只播 0.3 遍就上手的人要单独看」。
    把这一列定成整数，前端每次提交都被 422 挡下，而客户端的重试队列
    会把这一次失败放大成无限次重试：线上实测 321 个 422。
    """
    response = client.put(
        "/api/attempts/att-1",
        json=attempt_body(familiarization_plays=1.4),
        headers=assigned,
    )
    assert response.status_code == 200, response.text
    assert response.json()["familiarization_plays"] == pytest.approx(1.4)


def test_familiarization_plays_survives_a_round_trip(
    client: TestClient, session: Session, assigned
):
    """小数要真的存进库，不能在落库时被截成整数。"""
    client.put(
        "/api/attempts/att-1",
        json=attempt_body(familiarization_plays=0.3),
        headers=assigned,
    )
    listed = client.get("/api/attempts", headers=assigned).json()[0]
    assert listed["familiarization_plays"] == pytest.approx(0.3)
