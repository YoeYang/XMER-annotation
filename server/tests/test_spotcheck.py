"""每日抽查（2026-10-01 版）。"""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.models import (Annotator, Assignment, Attempt, AttemptFlag, SampleChunk,
                        Submission, Task)
from app.spotcheck import spot_check

ADMIN = {"Authorization": "Bearer admin-token"}
DAY = date(2026, 10, 2)
# 芬兰 10.2 中午 = UTC 09:00
NOON = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
RISE = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
_seq = iter(range(100_000))


def submit(session, aid, tid, dim, values, at, revision=1):
    att = f"x{next(_seq)}"
    session.add(Attempt(attempt_id=att, task_id=tid, annotator_id=aid, media_id=tid,
                        modality="face", mode="annotation", dimension=dim, status="completed",
                        task_snapshot={}, events=[], sample_rate_hz=10, started_at=at))
    session.flush()
    session.add(SampleChunk(attempt_id=att, chunk_index=0, samples=[
        {"media_time": round(i * 0.1, 1), "value": v, "is_valid": True}
        for i, v in enumerate(values)]))
    session.add(Submission(submission_id=att, task_id=tid, annotator_id=aid, attempt_id=att,
                           dimension=dim, revision=revision, submitted_at=at))
    session.flush()
    return att


def finish(session, aid, tid, at, valence=RISE, arousal=RISE):
    submit(session, aid, tid, "valence", valence, at - timedelta(seconds=10))
    return submit(session, aid, tid, "arousal", arousal, at)


@pytest.fixture
def world(session: Session):
    for aid in ("P1-EN-01", "REF-02"):
        session.add(Annotator(annotator_id=aid, token_hash=aid, phase="main", language="en"))
    for i in range(14):
        tid = f"S{i}::face"
        session.add(Task(task_id=tid, media_id=tid, source_id=f"S{i}", title=tid,
                         modality="face", src=f"/pool/v3/media/S{i}/face.mp4", duration=0.5))
    session.flush()
    for i in range(14):
        phase = "training" if i == 13 else "main"
        session.add(Assignment(annotator_id="P1-EN-01", task_id=f"S{i}::face", phase=phase,
                               order_index=i))
    session.flush()
    for i in range(12):
        finish(session, "P1-EN-01", f"S{i}::face", NOON + timedelta(minutes=i))
    session.commit()
    return session


def test_only_that_days_completed_subtasks(world):
    # 芬兰 10.2 00:30 = UTC 10.1 21:30 → 算 10.2；UTC 20:30 → 10.1
    finish(world, "P1-EN-01", "S12::face", datetime(2026, 10, 1, 21, 30, tzinfo=timezone.utc))
    finish(world, "P1-EN-01", "S13::face", datetime(2026, 10, 1, 20, 30, tzinfo=timezone.utc))
    world.commit()
    report = spot_check(world, "P1-EN-01", DAY, n=50)
    assert report["summary"]["completed"] == 13
    assert "S13::face" not in {i["task_id"] for i in report["items"]}


def test_half_done_is_not_sampled(world):
    submit(world, "P1-EN-01", "S12::face", "valence", RISE, NOON)
    world.commit()
    assert spot_check(world, "P1-EN-01", DAY, n=50)["summary"]["completed"] == 12


def test_samples_n_deterministically_in_completion_order(world):
    a = spot_check(world, "P1-EN-01", DAY, n=5, seed=3)
    b = spot_check(world, "P1-EN-01", DAY, n=5, seed=3)
    ids = [i["task_id"] for i in a["items"]]
    assert ids == [i["task_id"] for i in b["items"]] and len(ids) == 5
    assert [i["completed_at"] for i in a["items"]] == sorted(i["completed_at"] for i in a["items"])
    assert ids != [i["task_id"] for i in spot_check(world, "P1-EN-01", DAY, n=5, seed=4)["items"]]


def test_notes_flag_flat_narrow_and_many_redos(world):
    finish(world, "P1-EN-01", "S12::face", NOON + timedelta(hours=1),
           valence=[0.3] * 6, arousal=[0.0, 0.05, 0.1, 0.1, 0.05, 0.0])
    for rev in (2, 3):
        submit(world, "P1-EN-01", "S12::face", "valence", [0.3] * 6,
               NOON + timedelta(hours=1, minutes=rev), revision=rev)
    world.commit()
    item = next(i for i in spot_check(world, "P1-EN-01", DAY, n=50)["items"]
                if i["task_id"] == "S12::face")
    assert item["dims"]["valence"]["notes"] == ["几乎不动", "重标 3 版"]
    assert item["dims"]["arousal"]["notes"] == ["量程很窄"]
    assert item["dims"]["valence"]["revisions"] == 3


def test_anchor_gets_reference_but_training_does_not(world):
    for dim in ("valence", "arousal"):
        submit(world, "REF-02", "S0::face", dim, [v - 0.5 for v in RISE], NOON)
        submit(world, "REF-02", "S13::face", dim, RISE, NOON)
    finish(world, "P1-EN-01", "S13::face", NOON + timedelta(hours=2))
    world.commit()
    items = {i["task_id"]: i for i in spot_check(world, "P1-EN-01", DAY, n=50)["items"]}
    assert items["S0::face"]["dims"]["valence"]["vs_ref"]["mae"] == 0.5
    assert items["S13::face"]["phase"] == "training"
    assert items["S13::face"]["dims"]["valence"]["ref"] is None


def test_latest_flag_is_shown(world):
    att = finish(world, "P1-EN-01", "S12::face", NOON + timedelta(hours=3))
    world.add(AttemptFlag(attempt_id=att, flag="low_quality",
                          flagged_at=datetime(2026, 10, 2, 10, tzinfo=timezone.utc)))
    world.add(AttemptFlag(attempt_id=att, flag="ok",
                          flagged_at=datetime(2026, 10, 2, 11, tzinfo=timezone.utc)))
    world.commit()
    item = next(i for i in spot_check(world, "P1-EN-01", DAY, n=50)["items"]
                if i["task_id"] == "S12::face")
    assert item["dims"]["arousal"]["flag"] == "ok"


def test_summary(world):
    s = spot_check(world, "P1-EN-01", DAY)["summary"]
    assert s["completed"] == 12 and s["flat_share"] == 0.0 and s["mean_spread"] == 1.0


def test_empty_day(world):
    report = spot_check(world, "P1-EN-01", date(2026, 10, 5))
    assert report["items"] == [] and report["summary"]["completed"] == 0


def test_endpoint(client, world):
    assert client.get("/api/admin/spotcheck/P1-EN-01").status_code == 401
    assert client.get("/api/admin/spotcheck/NOPE", headers=ADMIN).status_code == 404
    body = client.get("/api/admin/spotcheck/P1-EN-01?day=2026-10-02&n=3",
                      headers=ADMIN).json()
    assert body["date"] == "2026-10-02" and len(body["items"]) == 3
