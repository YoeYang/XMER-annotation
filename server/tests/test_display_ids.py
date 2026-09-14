"""样本编号：标注者只看得到 S0001 这样的不透明编号。

编号一旦发出去就不能再变——标注结果按样本对齐，改号等于对不上账。
"""

from sqlalchemy.orm import Session

from app.assignments import assign_display_ids
from app.models import Assignment, Task

MODALITIES = ["visual", "audio", "text", "audiovisual"]


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
                    src=f"/pool/media/{source_id}/{modality}.mp4",
                    duration=4.0,
                )
            )
    session.commit()


def test_同一样本四个任务共用一个编号(session: Session) -> None:
    make_samples(session, [f"meld_dia{i}_utt0" for i in range(5)])

    mapping = assign_display_ids(session, seed=20260914)
    session.commit()

    assert len(mapping) == 5
    assert [display for display, _ in mapping] == [
        "S0001",
        "S0002",
        "S0003",
        "S0004",
        "S0005",
    ]
    for source_id in (sid for _, sid in mapping):
        ids = {
            task.display_id
            for task in session.query(Task).filter(Task.source_id == source_id)
        }
        assert len(ids) == 1 and ids.pop().startswith("S")


def test_编号顺序被打乱_不按数据集聚集(session: Session) -> None:
    # 字母序会让同一数据集连号，编号区间直接泄露样本来源
    source_ids = [f"chsims_{i:03d}" for i in range(20)] + [
        f"iemocap_{i:03d}" for i in range(20)
    ]
    make_samples(session, source_ids)

    mapping = dict(assign_display_ids(session, seed=20260914))
    session.commit()

    first_half = {mapping[f"S{i:04d}"].split("_")[0] for i in range(1, 21)}
    assert first_half == {"chsims", "iemocap"}


def test_重复执行不改动已有编号_新样本往后接(session: Session) -> None:
    make_samples(session, [f"meld_dia{i}_utt0" for i in range(3)])
    first = dict(assign_display_ids(session, seed=1))
    session.commit()

    make_samples(session, ["mosi_new_0001", "mosi_new_0002"])
    second = dict(assign_display_ids(session, seed=2))
    session.commit()

    for display_id, source_id in first.items():
        assert second[display_id] == source_id
    assert set(second) - set(first) == {"S0004", "S0005"}
    assert len(set(second.values())) == 5


def test_同一个种子给出同样的编号(session: Session, engine) -> None:
    from sqlalchemy.orm import Session as RawSession

    source_ids = [f"meld_dia{i}_utt0" for i in range(30)]
    make_samples(session, source_ids)
    once = assign_display_ids(session, seed=777)
    session.rollback()

    with RawSession(engine) as other:
        twice = assign_display_ids(other, seed=777)
        other.rollback()
    assert once == twice


def test_换令牌后旧链接失效_新链接可用且数据保留(
    client, session: Session, annotator
) -> None:
    """明文令牌丢了只能重发。重发不该动账号本身的任何数据。"""
    from app.auth import hash_token, new_token

    make_samples(session, ["meld_dia11_utt9"])
    session.add(
        Assignment(
            annotator_id=annotator.annotator_id,
            task_id="meld_dia11_utt9::visual",
            phase="pilot",
            order_index=0,
            is_anchor=False,
        )
    )
    session.commit()

    head = {"Authorization": "Bearer token-a001"}
    before = client.get("/api/me", headers=head)
    assert before.status_code == 200
    tasks_before = before.json()["tasks"]

    fresh = new_token()
    annotator.token_hash = hash_token(fresh)
    session.commit()

    assert client.get("/api/me", headers=head).status_code == 401
    after = client.get("/api/me", headers={"Authorization": f"Bearer {fresh}"})
    assert after.status_code == 200
    assert after.json()["annotator_id"] == annotator.annotator_id
    assert after.json()["tasks"] == tasks_before
