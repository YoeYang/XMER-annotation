"""锚点质量：标注者曲线与参考曲线的比对（2026-10-01 版）。"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.anchor_quality import anchor_report, compare, resample
from app.models import Annotator, Assignment, Attempt, SampleChunk, Submission, Task

ADMIN = {"Authorization": "Bearer admin-token"}
NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)


# ------------------------------------------------------------ 纯函数


def pts(*pairs, valid=True):
    return [{"media_time": t, "value": v, "is_valid": valid} for t, v in pairs]


def test_resample_holds_the_last_value():
    assert resample(pts((0, 0.0), (0.25, 1.0)), 0.4) == [0.0, 0.0, 0.0, 1.0, 1.0]


def test_resample_skips_invalid_samples():
    samples = pts((0, 0.0)) + pts((0.1, 9.0), valid=False)
    assert resample(samples, 0.2) == [0.0, 0.0, 0.0]


def test_resample_of_nothing_is_empty():
    assert resample([], 1.0) == []


def test_identical_curves():
    curve = [0.0, 0.5, 1.0, 0.5]
    assert compare(curve, curve) == {"mae": 0.0, "r": 1.0}


def test_offset_curves_have_mae_but_full_correlation():
    a = [0.0, 0.5, 1.0, 0.5]
    assert compare(a, [x - 0.5 for x in a]) == {"mae": 0.5, "r": 1.0}


def test_flat_curve_has_no_correlation():
    assert compare([0.3] * 5, [0.0, 0.2, 0.4, 0.2, 0.0])["r"] is None


def test_empty_side_gives_nothing():
    assert compare([], [0.1]) == {"mae": None, "r": None}


# ------------------------------------------------------------ 库里比对

_seq = iter(range(10_000))


def submit(session, aid, tid, dim, values, revision=1, at=NOW):
    n = next(_seq)
    att = f"a{n}"
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


RISE = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]


@pytest.fixture
def world(session: Session):
    for aid, phase in [("P1-EN-01", "main"), ("P1-ZH-01", "main"), ("REF-01", "pilot"),
                       ("REF-02", "pilot")]:
        session.add(Annotator(annotator_id=aid, token_hash=aid, phase=phase, language="zh"))
    for tid in ["A::face", "B::face", "T::face"]:
        session.add(Task(task_id=tid, media_id=tid, source_id=tid[0], title=tid,
                         modality="face", src="/x", duration=0.5))
    session.flush()
    rows = [("P1-EN-01", "A::face", "main", False), ("P1-ZH-01", "A::face", "main", False),
            ("P1-EN-01", "B::face", "main", False), ("P1-ZH-01", "B::face", "main", False),
            ("P1-EN-01", "T::face", "main", False), ("P1-EN-01", "T::face", "training", False),
            ("REF-02", "A::face", "pilot", True), ("REF-02", "B::face", "pilot", True)]
    for i, (aid, tid, phase, anchor) in enumerate(rows):
        session.add(Assignment(annotator_id=aid, task_id=tid, phase=phase, order_index=i,
                               is_anchor=anchor))
    session.flush()
    # A：参考两维都交了——锚点就绪
    submit(session, "REF-02", "A::face", "valence", RISE)
    submit(session, "REF-02", "A::face", "arousal", RISE)
    # B：参考只交了效价——还不算就绪
    submit(session, "REF-02", "B::face", "valence", RISE)
    # T：训练子任务，参考交了也不算锚点
    submit(session, "REF-01", "T::face", "valence", RISE)
    submit(session, "REF-01", "T::face", "arousal", RISE)
    session.commit()
    return session


def row(report, aid):
    return next(r for r in report["annotators"] if r["annotator_id"] == aid)


def test_only_finished_non_training_anchors_are_ready(world):
    report = anchor_report(world, 1)
    assert row(report, "P1-EN-01")["ready"] == 1
    assert row(report, "P1-EN-01")["compared"] == 0
    assert report["reference"] == {"queued": 2, "done": 1, "done_from_queue": 1}
    assert [r["annotator_id"] for r in report["annotators"]] == ["P1-EN-01", "P1-ZH-01"]


def test_scores_use_the_latest_versions(world):
    submit(world, "P1-EN-01", "A::face", "valence", [v - 0.3 for v in RISE])
    submit(world, "P1-EN-01", "A::face", "arousal", [0.5] * 6)
    # 参考重标了效价：比对必须换成新版
    submit(world, "REF-02", "A::face", "valence", [v - 0.3 for v in RISE], revision=2,
           at=NOW + timedelta(minutes=1))
    world.commit()
    r = row(anchor_report(world, 1), "P1-EN-01")
    assert r["compared"] == 1
    assert r["mae_valence"] == 0.0 and r["r_valence"] == 1.0
    assert r["mae_arousal"] == 0.3 and r["r_arousal"] is None


def test_detail_carries_both_curves(world):
    submit(world, "P1-ZH-01", "A::face", "valence", RISE)
    world.commit()
    detail = anchor_report(world, 1, detail_for="P1-ZH-01")["detail"]
    assert detail["annotator_id"] == "P1-ZH-01"
    item = detail["items"][0]
    assert item["task_id"] == "A::face" and "arousal" not in item
    assert item["valence"]["mine"] == item["valence"]["ref"] == RISE


def test_outlier_is_flagged_against_the_group(session: Session):
    people = ["P1-EN-01", "P1-EN-02", "P1-EN-03"]
    for aid in people + ["REF-02"]:
        session.add(Annotator(annotator_id=aid, token_hash=aid, phase="main", language="en"))
    for i in range(6):
        tid = f"S{i}::face"
        session.add(Task(task_id=tid, media_id=tid, source_id=f"S{i}", title=tid,
                         modality="face", src="/x", duration=0.5))
    session.flush()
    for i in range(6):
        tid = f"S{i}::face"
        for j, aid in enumerate(people):
            session.add(Assignment(annotator_id=aid, task_id=tid, phase="main", order_index=i))
        for dim in ("valence", "arousal"):
            submit(session, "REF-02", tid, dim, RISE)
            submit(session, "P1-EN-01", tid, dim, [v + 0.05 for v in RISE])
            submit(session, "P1-EN-02", tid, dim, [v - 0.05 for v in RISE])
            submit(session, "P1-EN-03", tid, dim, [-v for v in RISE])
    session.commit()
    report = anchor_report(session, 1)
    assert [r["annotator_id"] for r in report["annotators"] if r["outlier"]] == ["P1-EN-03"]


def test_endpoints(client, world):
    assert client.get("/api/admin/anchors").status_code == 401
    assert client.get("/api/admin/anchors?stage=1", headers=ADMIN).json()["stage"] == 1
    assert client.get("/api/admin/anchors/NOPE", headers=ADMIN).status_code == 404
    body = client.get("/api/admin/anchors/P1-EN-01", headers=ADMIN).json()
    assert body["detail"]["annotator_id"] == "P1-EN-01"
