"""参考曲线：训练页拿来和标注者自己的曲线对照的那条线。

两件事是硬要求，这批测试把它们钉死：

1. **两个维度都提交之后才放出来**，而且由**服务端**拦。先看到效价的参考
   曲线再标唤醒等于给了答案，而「前端不显示」拦不住直接请求接口的人——
   训练结果要用来判断这个人标得准不准，能被绕开的闸等于没有。
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
                samples=[{"t": 0.0, "v": value}],
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


# --------------------------------------------------------------- 放出的时机


def test_one_dimension_is_not_enough(client, session, trainee, task):
    seed_reference(session, task.task_id)
    submit(session, "T001", task.task_id, "valence", attempt="a1")
    response = client.get(f"/api/training/reference/{task.task_id}", headers=trainee)
    assert response.status_code == 403


def test_both_dimensions_open_it(client, session, trainee, task):
    seed_reference(session, task.task_id)
    submit(session, "T001", task.task_id, "valence", attempt="a1")
    submit(session, "T001", task.task_id, "arousal", attempt="a2", minutes=1)
    response = client.get(f"/api/training/reference/{task.task_id}", headers=trainee)
    assert response.status_code == 200
    body = response.json()
    # 效价在前、唤醒在后，与标注顺序一致；按插入顺序返回会是反的
    assert [t["dimension"] for t in body["traces"]] == ["valence", "arousal"]
    assert body["traces"][0]["note_zh"] == "参考说明"


def test_non_training_accounts_never_see_it(client, session, assigned, task):
    """正式阶段的账号一律拒绝：校准样本若混进正式队列，更不能给看。"""
    seed_reference(session, task.task_id)
    submit(session, "A001", task.task_id, "valence", attempt="a1")
    submit(session, "A001", task.task_id, "arousal", attempt="a2", minutes=1)
    response = client.get(f"/api/training/reference/{task.task_id}", headers=assigned)
    assert response.status_code == 403


def test_unassigned_task_is_not_found(client, session, trainee, second_task):
    seed_reference(session, second_task.task_id)
    response = client.get(
        f"/api/training/reference/{second_task.task_id}", headers=trainee
    )
    assert response.status_code == 404


def test_task_without_a_reference_says_so(client, session, trainee, task):
    submit(session, "T001", task.task_id, "valence", attempt="a1")
    submit(session, "T001", task.task_id, "arousal", attempt="a2", minutes=1)
    response = client.get(f"/api/training/reference/{task.task_id}", headers=trainee)
    assert response.status_code == 404


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


def test_admin_listing_joins_media_and_notes(client, session, task):
    """曲线、素材地址、解释必须一次取齐——分开取就要页面自己对 task_id，
    对错了看不出来，文字会挂到别的样本下面。"""
    from app.models import SampleNumber

    session.add(SampleNumber(display_id="S0042", source_id=task.source_id))
    seed_reference(session, task.task_id)
    response = client.get(
        "/api/admin/reference", headers={"Authorization": "Bearer admin-token"}
    )
    assert response.status_code == 200
    entry = response.json()["tasks"][0]
    assert entry["display_id"] == "S0042"
    assert entry["src"] == task.src
    assert [t["dimension"] for t in entry["traces"]] == ["valence", "arousal"]
    # 采样点只留时间与取值；原始记录里的 attempt_id、wall_time 白撑响应
    assert set(entry["traces"][0]["points"][0]) == {"t", "v"}


def test_admin_listing_needs_the_token(client, session, task):
    seed_reference(session, task.task_id)
    assert client.get("/api/admin/reference").status_code == 401


def test_note_edit_leaves_the_curve_alone(client, session, task):
    """改文字的页面不该有能力覆盖曲线——曲线来自真实标注。"""
    seed_reference(session, task.task_id)
    before = session.get(ReferenceTrace, (task.task_id, "valence")).samples
    response = client.put(
        f"/api/admin/reference/{task.task_id}/valence",
        headers={"Authorization": "Bearer admin-token"},
        json={"note_zh": "改过了", "note_en": "edited", "note_fi": "muokattu"},
    )
    assert response.status_code == 200
    session.expire_all()
    row = session.get(ReferenceTrace, (task.task_id, "valence"))
    assert row.note_zh == "改过了"
    assert row.samples == before


def test_blank_note_becomes_null(client, session, task):
    """「还没写」和「写了个空」要分得开，否则导入脚本判断不了该不该覆盖。"""
    seed_reference(session, task.task_id)
    client.put(
        f"/api/admin/reference/{task.task_id}/valence",
        headers={"Authorization": "Bearer admin-token"},
        json={"note_zh": "   ", "note_en": "", "note_fi": ""},
    )
    session.expire_all()
    assert session.get(ReferenceTrace, (task.task_id, "valence")).note_zh is None


def test_editing_a_missing_trace_is_not_found(client, session, task):
    response = client.put(
        f"/api/admin/reference/{task.task_id}/valence",
        headers={"Authorization": "Bearer admin-token"},
        json={"note_zh": "x"},
    )
    assert response.status_code == 404


def test_import_keeps_notes_written_in_the_review_page(session: Session, annotator, task):
    """整批重跑不许覆盖手写的解释。

    解释多半是后来在校对页上一条条写的，而这条命令是按名单整批重跑的。
    整行覆盖会把手写稿静悄悄抹掉，等打开训练页才发现。
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
