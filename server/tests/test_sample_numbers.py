"""样本编号只有一套，一一对应由数据库保证。

编号原先是 `tasks.display_id` 上的一个普通列：同一样本的五个任务各存一份，
数据库拦不住「S0001 同时挂在两个样本上」，也拦不住「一个样本有两个号」。
演示数据 `public/tasks.json` 里的 DEMO 就占着正式表的 S0001——
靠约定维持的唯一性迟早会被某次导入捅破。

现在编号独立成 `sample_numbers` 表：`display_id` 是主键，`source_id` 唯一，
一一对应由主键与唯一约束兜底，`tasks` 不再存副本。
"""
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.assignments import assign_display_ids, issue_numbers
from app.models import SampleNumber, Task

MODALITIES = ["face", "body", "audio", "text", "audiovisual"]


def make_samples(session: Session, source_ids: list[str]) -> None:
    for source_id in source_ids:
        for modality in MODALITIES:
            session.add(
                Task(
                    task_id=f"{source_id}::{modality}",
                    media_id=f"{source_id}-{modality}",
                    source_id=source_id,
                    title=f"{source_id} · {modality}",
                    modality=modality,
                    src=f"/pool/v3/media/{source_id}/{modality}.mp4",
                    duration=4.0,
                )
            )
    session.commit()


# ------------------------------------------------------- 一一对应由数据库保证


def test_one_number_cannot_serve_two_samples(session: Session):
    session.add(SampleNumber(display_id="S0001", source_id="a"))
    session.commit()
    session.add(SampleNumber(display_id="S0001", source_id="b"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_one_sample_cannot_hold_two_numbers(session: Session):
    session.add(SampleNumber(display_id="S0001", source_id="a"))
    session.commit()
    session.add(SampleNumber(display_id="S0002", source_id="a"))
    with pytest.raises(IntegrityError):
        session.commit()


# ------------------------------------------------------------------- 发号


def test_numbers_are_issued_to_samples_without_one(session: Session):
    make_samples(session, [f"meld_dia{i}_utt0" for i in range(5)])
    mapping = assign_display_ids(session, seed=1)
    session.commit()

    assert len(mapping) == 5
    assert sorted(d for d, _ in mapping) == ["S0001", "S0002", "S0003", "S0004", "S0005"]


def test_existing_numbers_are_never_reassigned(session: Session):
    """编号发出去就固定。重发会让先前提交的结果对到错的样本上。"""
    make_samples(session, ["a", "b"])
    first = dict((s, d) for d, s in assign_display_ids(session, seed=1))
    session.commit()

    make_samples(session, ["c"])
    second = dict((s, d) for d, s in assign_display_ids(session, seed=2))
    session.commit()

    assert second["a"] == first["a"] and second["b"] == first["b"]
    assert second["c"] not in first.values()


def test_new_samples_continue_after_the_highest_number(session: Session):
    session.add(SampleNumber(display_id="S3441", source_id="old"))
    session.commit()
    make_samples(session, ["fresh"])
    mapping = dict((s, d) for d, s in assign_display_ids(session, seed=1))
    session.commit()
    assert mapping["fresh"] == "S3442"


def test_issuing_can_start_from_a_chosen_number(session: Session):
    """备份池从 S3500 起发，与主池的 S0001–S3441 隔开一段，一眼能分辨。"""
    session.add(SampleNumber(display_id="S3441", source_id="old"))
    session.commit()
    issued = issue_numbers(session, ["backup_a", "backup_b"], start=3500, seed=1)
    session.commit()
    assert sorted(d for d, _ in issued) == ["S3500", "S3501"]


def test_starting_below_the_highest_number_is_refused(session: Session):
    """从已用过的号段起发会撞号，必须当场拒绝而不是跳着发。"""
    session.add(SampleNumber(display_id="S3441", source_id="old"))
    session.commit()
    with pytest.raises(ValueError):
        issue_numbers(session, ["x"], start=100, seed=1)


def test_reissuing_an_already_numbered_sample_is_a_no_op(session: Session):
    session.add(SampleNumber(display_id="S0007", source_id="a"))
    session.commit()
    issued = issue_numbers(session, ["a"], start=3500, seed=1)
    session.commit()
    assert issued == []
    assert session.get(SampleNumber, "S0007").source_id == "a"


# ------------------------------------------------------------------- 退役


def test_retired_numbers_are_kept_and_never_reused(session: Session):
    """样本退出池子，编号保留并标 retired；空出的号绝不重发。"""
    session.add(SampleNumber(display_id="S0001", source_id="gone", status="retired"))
    session.commit()
    make_samples(session, ["fresh"])
    mapping = dict((s, d) for d, s in assign_display_ids(session, seed=1))
    session.commit()
    assert mapping["fresh"] != "S0001"
