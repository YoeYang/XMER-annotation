from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Annotator,
    Assignment,
    Attempt,
    AttemptFlag,
    SampleChunk,
    Submission,
    Task,
)

NOW = datetime.now(timezone.utc)


def test_speaker_ref_is_persisted(session: Session, task: Task):
    """静帧参考由预处理产出，必须能随任务下发给标注者。"""
    loaded = session.get(Task, "EXAMPLE-001")
    assert loaded.speaker_ref_src == "/media/example/speaker.jpg"
    assert loaded.speaker_name == "Phoebe"


def test_chunk_primary_key_rejects_replay(session: Session, attempt: Attempt):
    """幂等基石：同一 (attempt_id, chunk_index) 重传必须被拒，不产生重复采样。"""
    session.add(SampleChunk(attempt_id=attempt.attempt_id, chunk_index=0, samples=[1]))
    session.commit()
    session.add(SampleChunk(attempt_id=attempt.attempt_id, chunk_index=0, samples=[2]))
    with pytest.raises(IntegrityError):
        session.commit()


def test_chunks_reassemble_in_index_order(session: Session, attempt: Attempt):
    """乱序到达的块，按 chunk_index 拼接后仍还原出正确轨迹。"""
    for index in (2, 0, 1):
        session.add(
            SampleChunk(
                attempt_id=attempt.attempt_id,
                chunk_index=index,
                samples=[{"sample_index": index}],
            )
        )
    session.commit()

    rows = session.scalars(
        select(SampleChunk)
        .where(SampleChunk.attempt_id == attempt.attempt_id)
        .order_by(SampleChunk.chunk_index)
    ).all()
    assert [r.samples[0]["sample_index"] for r in rows] == [0, 1, 2]


def test_submission_chain_keeps_history(
    session: Session,
    annotator: Annotator,
    task: Task,
    attempt: Attempt,
    second_attempt: Attempt,
):
    """Update 另开轮次形成新版本并指回上一版，旧提交仍然可查。"""
    first = Submission(
        submission_id="sub-1",
        task_id=task.task_id,
        annotator_id=annotator.annotator_id,
        attempt_id=attempt.attempt_id,
        revision=1,
        submitted_at=NOW,
    )
    session.add(first)
    session.commit()

    second = Submission(
        submission_id="sub-2",
        task_id=task.task_id,
        annotator_id=annotator.annotator_id,
        attempt_id=second_attempt.attempt_id,
        revision=2,
        previous_submission_id="sub-1",
        submitted_at=NOW,
        updated_at=NOW,
    )
    session.add(second)
    session.commit()

    assert session.get(Submission, "sub-1") is not None
    assert session.get(Submission, "sub-2").previous_submission_id == "sub-1"


def test_submission_revision_is_unique_per_task(
    session: Session,
    annotator: Annotator,
    task: Task,
    attempt: Attempt,
    second_attempt: Attempt,
):
    """同一标注者对同一任务不能出现两个 revision 1——重复提交去重的底线。"""
    for submission_id, source in (
        ("sub-1", attempt),
        ("sub-1-replay", second_attempt),
    ):
        session.add(
            Submission(
                submission_id=submission_id,
                task_id=task.task_id,
                annotator_id=annotator.annotator_id,
                attempt_id=source.attempt_id,
                revision=1,
                submitted_at=NOW,
            )
        )
    with pytest.raises(IntegrityError):
        session.commit()


def test_assignment_is_unique_per_phase(
    session: Session, annotator: Annotator, task: Task
):
    """同一阶段内不重复分配，但同一样本可以在不同阶段再次出现（锚点复标）。"""
    session.add(
        Assignment(
            annotator_id=annotator.annotator_id,
            task_id=task.task_id,
            phase="pilot",
            order_index=0,
        )
    )
    session.add(
        Assignment(
            annotator_id=annotator.annotator_id,
            task_id=task.task_id,
            phase="main",
            order_index=42,
            is_anchor=True,
        )
    )
    session.commit()

    duplicate = Assignment(
        annotator_id=annotator.annotator_id,
        task_id=task.task_id,
        phase="pilot",
        order_index=7,
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        session.commit()


def test_anchor_flag_defaults_to_false(
    session: Session, annotator: Annotator, task: Task
):
    session.add(
        Assignment(
            annotator_id=annotator.annotator_id,
            task_id=task.task_id,
            phase="pilot",
            order_index=0,
        )
    )
    session.commit()
    row = session.scalars(select(Assignment)).one()
    assert row.is_anchor is False


@pytest.mark.parametrize(
    "field,value",
    [("phase", "production"), ("phase", "")],
)
def test_annotator_phase_is_constrained(session: Session, field: str, value: str):
    """阶段只能是 pilot/training/main，写错阶段会让分配和锚点统计全部错位。"""
    session.add(
        Annotator(annotator_id="A999", token_hash="hash-a999", **{field: value})
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_attempt_requires_existing_annotator(session: Session, task: Task):
    """孤儿轮次会让导出对不上人，外键必须拦住。"""
    session.add(
        Attempt(
            attempt_id="att-orphan",
            task_id=task.task_id,
            annotator_id="A-does-not-exist",
            media_id=task.media_id,
            modality=task.modality,
            mode="annotation",
            status="recording",
            task_snapshot={},
            events=[],
            sample_rate_hz=10,
            started_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_attempt_flag_history_is_kept(session: Session, attempt: Attempt):
    """同一轮次可被多次标记，保留完整处置历史。"""
    session.add(
        AttemptFlag(attempt_id=attempt.attempt_id, flag="low_quality", flagged_by="研究者")
    )
    session.add(
        AttemptFlag(attempt_id=attempt.attempt_id, flag="void", note="说话人指错")
    )
    session.commit()
    rows = session.scalars(select(AttemptFlag)).all()
    assert {r.flag for r in rows} == {"low_quality", "void"}


def test_attempt_flag_rejects_unknown_value(session: Session, attempt: Attempt):
    session.add(AttemptFlag(attempt_id=attempt.attempt_id, flag="maybe"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_one_submission_per_attempt(
    session: Session, annotator: Annotator, task: Task, attempt: Attempt
):
    """一轮次一提交：换个 submission_id 也不能给同一轮次再提交一次。"""
    for submission_id, revision in (("sub-1", 1), ("sub-other", 2)):
        session.add(
            Submission(
                submission_id=submission_id,
                task_id=task.task_id,
                annotator_id=annotator.annotator_id,
                attempt_id=attempt.attempt_id,
                revision=revision,
                submitted_at=NOW,
            )
        )
    with pytest.raises(IntegrityError):
        session.commit()


# --------------------------------------------------------- V3：维度与五模态


def test_attempt_rejects_unknown_dimension(session, annotator, task):
    """一轮只标一个维度，写进来的必须是 valence / arousal 之一。"""
    session.add(
        Attempt(
            attempt_id="att-bad-dim",
            task_id=task.task_id,
            annotator_id=annotator.annotator_id,
            media_id=task.media_id,
            modality=task.modality,
            mode="annotation",
            dimension="both",
            status="recording",
            task_snapshot={},
            events=[],
            sample_rate_hz=10,
            started_at=datetime.now(timezone.utc),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_task_rejects_retired_visual_modality(session):
    """V3 把 visual 拆成了 face / body，旧模态名不该还能写进来——
    放行就等于让两种范式的数据混在一张表里。"""
    session.add(
        Task(
            task_id="EX-OLD",
            media_id="m-old",
            source_id="meld_dia11_utt9",
            title="旧模态",
            modality="visual",
            src="/media/x",
            duration=1.0,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_familiarization_plays_defaults_to_zero(session, annotator, task):
    """熟悉页播放次数是质检信号，没上报时记 0 而不是空。"""
    row = Attempt(
        attempt_id="att-fam",
        task_id=task.task_id,
        annotator_id=annotator.annotator_id,
        media_id=task.media_id,
        modality=task.modality,
        mode="annotation",
        dimension="arousal",
        status="recording",
        task_snapshot={},
        events=[],
        sample_rate_hz=10,
        started_at=datetime.now(timezone.utc),
    )
    session.add(row)
    session.commit()
    assert row.familiarization_plays == 0
