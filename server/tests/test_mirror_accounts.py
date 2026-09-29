"""管理员镜像号 ADMIN-ZH-01 / ADMIN-EN-01（2026-09-29 版）。

队列照抄某位标注者，页面一比一；但不受训练关卡约束，可在训练页与正式页之间
切换，训练复盘不等交齐就能看。
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

import manage
from app.auth import hash_token
from app.models import Annotator, Assignment, Task

MIRROR = {"Authorization": "Bearer token-admin"}
NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)


@pytest.fixture
def world(session: Session):
    session.add(Annotator(annotator_id="P1-ZH-01", token_hash=hash_token("token-p1"),
                          phase="main", language="zh"))
    session.add(Annotator(annotator_id="ADMIN-ZH-01", token_hash=hash_token("token-admin"),
                          phase="main", language="zh"))
    for task_id, modality in [("TR-face", "face"), ("TR-audio", "audio"),
                              ("MAIN-1", "face"), ("MAIN-2", "text")]:
        session.add(Task(task_id=task_id, media_id=task_id, source_id=f"src-{task_id}",
                         title=task_id, modality=modality, src="/x", duration=1.0))
    session.flush()
    for task_id, phase, order in [("TR-face", "training", 0), ("TR-audio", "training", 1),
                                  ("MAIN-1", "main", 0), ("MAIN-2", "main", 1)]:
        session.add(Assignment(annotator_id="P1-ZH-01", task_id=task_id,
                               phase=phase, order_index=order))
    session.commit()
    args = SimpleNamespace(source="P1-ZH-01", to="ADMIN-ZH-01")
    with patch("manage.session_factory", return_value=lambda: session):
        manage.cmd_mirror_queue(args)
    return session


def me(client, view=None):
    url = "/api/me" + (f"?view={view}" if view else "")
    body = client.get(url, headers=MIRROR).json()
    return body["phase"], [t["task_id"] for t in body["tasks"]], body["mirror"]


def attempt_body(task_id):
    return {"task_id": task_id, "media_id": task_id, "modality": "face",
            "mode": "annotation", "dimension": "valence", "status": "recording",
            "task_snapshot": {"task_id": task_id}, "sample_rate_hz": 10,
            "started_at": NOW.isoformat()}


def test_mirror_copies_both_queues_in_order(world):
    rows = world.query(Assignment).filter_by(annotator_id="ADMIN-ZH-01").all()
    got = sorted((r.phase, r.order_index, r.task_id) for r in rows)
    assert got == [("main", 0, "MAIN-1"), ("main", 1, "MAIN-2"),
                   ("training", 0, "TR-face"), ("training", 1, "TR-audio")]


def test_mirror_opens_on_main_without_training(client, world):
    """管理员不标注，不能被训练关卡挡在正式页外面。"""
    assert me(client) == ("main", ["MAIN-1", "MAIN-2"], True)


def test_mirror_can_switch_to_the_training_page(client, world):
    assert me(client, "training") == ("training", ["TR-face", "TR-audio"], True)


def test_mirror_can_open_tasks_of_both_phases(client, world):
    for i, task_id in enumerate(("TR-face", "MAIN-1")):
        response = client.put(f"/api/attempts/m{i}", json=attempt_body(task_id), headers=MIRROR)
        assert response.status_code == 200, task_id


def test_mirror_sees_the_debrief_without_finishing(client, world):
    body = client.get("/api/training/debrief/face", headers=MIRROR)
    assert body.status_code == 200
    assert all(pair["mine"] == [] for item in body.json()["items"] for pair in item["pairs"])


def test_mirror_never_gets_trained_at(client, world):
    me(client, "training")
    me(client)
    world.expire_all()
    assert world.get(Annotator, "ADMIN-ZH-01").trained_at is None


def test_view_is_ignored_for_real_annotators(client, world):
    body = client.get("/api/me?view=main", headers={"Authorization": "Bearer token-p1"}).json()
    assert body["phase"] == "training" and body["mirror"] is False


def test_mirror_queue_refuses_a_real_annotator_as_target(world):
    """照抄是整体替换、不走开工保护，只能对镜像号做。"""
    args = SimpleNamespace(source="ADMIN-ZH-01", to="P1-ZH-01")
    with patch("manage.session_factory", return_value=lambda: world):
        with pytest.raises(SystemExit):
            manage.cmd_mirror_queue(args)


def test_mirror_language_must_match_its_id(session, tmp_path):
    args = SimpleNamespace(count=1, stage=None, language="en", phase="main", prefix="ADMIN-ZH",
                           display_name_prefix="", base_url="https://x",
                           out=str(tmp_path / "a.csv"))
    with patch("manage.session_factory", return_value=lambda: session):
        with pytest.raises(SystemExit):
            manage.cmd_create_annotators(args)
