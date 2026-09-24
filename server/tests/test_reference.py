"""参考曲线：训练页拿来和标注者自己的曲线对照的那条线。

两件事是硬要求，这批测试把它们钉死：

1. **整段两维都交齐才放出来**，而且由**服务端**拦（见文末的分段复盘）。
   先看到参考曲线再标这一段后面几条等于给了答案，而「前端不显示」拦不住
   直接请求接口的人——训练结果要用来判断这个人标得准不准，
   能被绕开的闸等于没有。
2. **只取每条链的最新一版**。校准样本往往要反复标几遍才满意，
   导进旧版本就是拿一条被本人否掉的曲线去教别人。
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Annotator,
    Assignment,
    Attempt,
    ReferenceTrace,
    SampleChunk,
    Submission,
)

NOW = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)


def submit(session, annotator, task, dimension, *, attempt, revision=1, minutes=0,
           samples=None):
    session.add(
        Attempt(
            attempt_id=attempt, task_id=task, annotator_id=annotator,
            media_id="m", modality="face", mode="annotation",
            dimension=dimension, status="completed", task_snapshot={}, events=[],
            sample_rate_hz=10, started_at=NOW + timedelta(minutes=minutes),
        )
    )
    if samples:
        session.add(SampleChunk(attempt_id=attempt, chunk_index=0, samples=samples))
    session.add(
        Submission(
            submission_id=f"sub-{attempt}", task_id=task, annotator_id=annotator,
            attempt_id=attempt, dimension=dimension, revision=revision,
            submitted_at=NOW + timedelta(minutes=minutes),
        )
    )
    session.commit()


def seed_reference(session, task_id):
    for dimension, value in (("arousal", 0.4), ("valence", -0.8)):
        session.add(
            ReferenceTrace(
                task_id=task_id, dimension=dimension,
                # 参考曲线存的是**原始采样记录**（导入时直接来自 assemble_samples），
                # 不是画图用的瘦身形式。夹具写成瘦身形式的话，接口那层的字段名
                # 取错了测试也照样绿。
                samples=[{"media_time": 0.0, "value": value, "is_valid": True}],
                note_zh="参考说明", note_en="reference note", note_fi="viite",
            )
        )
    session.commit()


@pytest.fixture
def trainee(session: Session, task) -> dict[str, str]:
    """训练阶段的账号，已分配到 EXAMPLE-001。"""
    from app.auth import hash_token

    session.add(
        Annotator(annotator_id="T001", token_hash=hash_token("token-t001"),
                  phase="training", language="zh")
    )
    session.add(
        Assignment(annotator_id="T001", task_id=task.task_id,
                   phase="training", order_index=0)
    )
    session.commit()
    return {"Authorization": "Bearer token-t001"}


# --------------------------------------------------------------- 语言标签


def test_language_defaults_to_english(session: Session):
    """漏设的人只会拿到与语言无关的子任务；默认成 zh 才是坏得无声无息。"""
    from app.auth import hash_token

    row = Annotator(annotator_id="X1", token_hash=hash_token("t-x1"), phase="pilot")
    session.add(row)
    session.commit()
    assert row.language == "en"


def test_unknown_language_is_rejected(session: Session):
    from app.auth import hash_token

    session.add(
        Annotator(annotator_id="X2", token_hash=hash_token("t-x2"),
                  phase="pilot", language="de")
    )
    with pytest.raises(IntegrityError):
        session.commit()


# --------------------------------------------------------------- 导入


def test_import_takes_only_the_newest_revision(session: Session, annotator, task):
    """重标过的校准样本，导进去的必须是最后那一版。"""
    from manage import cmd_import_reference
    from types import SimpleNamespace
    from unittest.mock import patch

    submit(session, "A001", task.task_id, "valence", attempt="old", revision=1,
           samples=[{"t": 0.0, "v": 0.1}])
    submit(session, "A001", task.task_id, "valence", attempt="new", revision=2,
           minutes=5, samples=[{"t": 0.0, "v": 0.9}])
    submit(session, "A001", task.task_id, "arousal", attempt="ar", revision=1,
           minutes=6, samples=[{"t": 0.0, "v": -0.5}])

    args = SimpleNamespace(annotator_id="A001", tasks="", notes="")
    with patch("manage.session_factory", return_value=lambda: session):
        cmd_import_reference(args)

    rows = {r.dimension: r for r in session.query(ReferenceTrace).all()}
    assert rows["valence"].source_attempt_id == "new"
    assert rows["valence"].samples == [{"t": 0.0, "v": 0.9}]
    assert rows["arousal"].samples == [{"t": 0.0, "v": -0.5}]


def test_import_skips_an_empty_trace(session: Session, annotator, task):
    """没有采样点的提交不该变成一条「参考曲线」——那是条空线，教不了任何事。"""
    from manage import cmd_import_reference
    from types import SimpleNamespace
    from unittest.mock import patch

    submit(session, "A001", task.task_id, "valence", attempt="empty", revision=1)
    args = SimpleNamespace(annotator_id="A001", tasks="", notes="")
    with patch("manage.session_factory", return_value=lambda: session):
        cmd_import_reference(args)
    assert session.query(ReferenceTrace).count() == 0


# --------------------------------------------------------------- 校对页接口


def test_import_keeps_notes_written_by_hand(session: Session, annotator, task):
    """整批重跑不许覆盖手写的解释。

    解释是一条条手写的，而这条命令是按名单整批重跑的。整行覆盖会把手写稿
    静悄悄抹掉，等打开训练页才发现。校对页已经撤掉，改文字的正路是改
    `plans/reference_notes.json` 再带 --replace-notes 重跑——那条路更要
    分得清「补空缺」和「覆盖」。
    """
    from manage import cmd_import_reference
    from types import SimpleNamespace
    from unittest.mock import patch
    import json
    import tempfile

    submit(session, "A001", task.task_id, "valence", attempt="a1",
           samples=[{"t": 0.0, "v": 0.5}])
    session.add(
        ReferenceTrace(task_id=task.task_id, dimension="valence",
                       samples=[], note_zh="手写的解释")
    )
    session.commit()

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump({task.task_id: {"valence": {"zh": "JSON 里的旧稿", "en": "draft"}}},
                  handle)
        notes_path = handle.name

    args = SimpleNamespace(annotator_id="A001", tasks="", notes=notes_path,
                           replace_notes=False)
    with patch("manage.session_factory", return_value=lambda: session):
        cmd_import_reference(args)

    session.expire_all()
    row = session.get(ReferenceTrace, (task.task_id, "valence"))
    assert row.note_zh == "手写的解释"       # 没被覆盖
    assert row.note_en == "draft"            # 空缺照样补上
    assert row.samples == [{"t": 0.0, "v": 0.5}]  # 曲线仍会刷新


def test_replace_notes_overrides_on_purpose(session: Session, annotator, task):
    from manage import cmd_import_reference
    from types import SimpleNamespace
    from unittest.mock import patch
    import json
    import tempfile

    submit(session, "A001", task.task_id, "valence", attempt="a1",
           samples=[{"t": 0.0, "v": 0.5}])
    session.add(
        ReferenceTrace(task_id=task.task_id, dimension="valence",
                       samples=[], note_zh="手写的解释")
    )
    session.commit()

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump({task.task_id: {"valence": {"zh": "换成这个"}}}, handle)
        notes_path = handle.name

    args = SimpleNamespace(annotator_id="A001", tasks="", notes=notes_path,
                           replace_notes=True)
    with patch("manage.session_factory", return_value=lambda: session):
        cmd_import_reference(args)

    session.expire_all()
    assert session.get(ReferenceTrace, (task.task_id, "valence")).note_zh == "换成这个"


# --------------------------------------------------------------- 分段复盘


def seed_block(session, trainee_id, tasks, *, complete=True):
    """给一位训练标注者铺一段：分配 + 两维提交 + 参考曲线。"""
    for index, task in enumerate(tasks):
        # trainee 夹具已经分配过第一条，重复插入会撞唯一约束
        existing = session.query(Assignment).filter_by(
            annotator_id=trainee_id, task_id=task.task_id, phase="training"
        ).one_or_none()
        if existing:
            existing.order_index = index
        else:
            session.add(
                Assignment(annotator_id=trainee_id, task_id=task.task_id,
                           phase="training", order_index=index)
            )
        seed_reference(session, task.task_id)
        dims = ("valence", "arousal") if complete else ("valence",)
        for dimension in dims:
            submit(session, trainee_id, task.task_id, dimension,
                   attempt=f"{task.task_id}-{dimension}", minutes=index,
                   samples=[{"media_time": 0.0, "value": 0.3, "is_valid": True}])
    session.commit()


def test_debrief_returns_both_curves_and_the_note(client, session, trainee, task):
    """素材、自己的曲线、参考曲线、解释一次取齐——分几个接口的话前端要自己
    按 task_id 对起来，对错了看不出来，曲线会画到别的样本下面。"""
    seed_block(session, "T001", [task])
    response = client.get("/api/training/debrief/face", headers=trainee)
    assert response.status_code == 200
    body = response.json()
    assert body["modality"] == "face"
    item = body["items"][0]
    assert item["src"] == task.src
    pair = item["pairs"][0]
    assert pair["dimension"] == "valence"
    assert pair["mine"] == [{"t": 0.0, "v": 0.3}]
    assert pair["reference"] == [{"t": 0.0, "v": -0.8}]
    assert pair["note_zh"] == "参考说明"


def test_debrief_waits_until_the_whole_block_is_done(client, session, trainee, task):
    """一条没标完就不给整段——先看到参考曲线再标后面几条等于给了答案。"""
    seed_block(session, "T001", [task], complete=False)
    response = client.get("/api/training/debrief/face", headers=trainee)
    assert response.status_code == 403
    assert "没标完" in response.json()["detail"]


def test_debrief_is_training_only(client, session, assigned, task):
    seed_reference(session, task.task_id)
    submit(session, "A001", task.task_id, "valence", attempt="v")
    submit(session, "A001", task.task_id, "arousal", attempt="a", minutes=1)
    assert client.get("/api/training/debrief/face", headers=assigned).status_code == 403


def test_debrief_of_an_unassigned_modality_is_not_found(client, session, trainee, task):
    seed_block(session, "T001", [task])
    assert client.get("/api/training/debrief/audio", headers=trainee).status_code == 404


def test_debrief_rejects_an_unknown_modality(client, session, trainee, task):
    seed_block(session, "T001", [task])
    assert client.get("/api/training/debrief/nose", headers=trainee).status_code == 404


def test_debrief_keeps_the_queue_order(client, session, trainee, task, second_task):
    """两条的先后要和队列一致，否则复盘里看到的顺序和刚标的顺序对不上。"""
    second_task.modality = "face"
    session.commit()
    seed_block(session, "T001", [second_task, task])
    body = client.get("/api/training/debrief/face", headers=trainee).json()
    assert [i["task_id"] for i in body["items"]] == [
        second_task.task_id, task.task_id
    ]
