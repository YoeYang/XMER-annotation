"""正式标注者编号 P<阶段>-<语言>-<序号>（2026-09-29 版）。

编号里的语言与库里的 `language` 必须一致；号只发不收，补招的人往后编；
`plan` 按编号前缀取某一阶段的人。
"""
import csv
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

import manage
from app.models import Annotator


def add(session: Session, annotator_id, language, phase="main", active=True):
    session.add(
        Annotator(annotator_id=annotator_id, token_hash=f"h-{annotator_id}",
                  phase=phase, language=language, active=active)
    )
    session.commit()


def create(session: Session, tmp_path, **kw):
    args = SimpleNamespace(count=1, stage=None, language="en", phase=None, prefix=None,
                           display_name_prefix="", base_url="https://x/annotation",
                           out=str(tmp_path / "accounts.csv"))
    for key, value in kw.items():
        setattr(args, key, value)
    with patch("manage.session_factory", return_value=lambda: session):
        manage.cmd_create_annotators(args)
    with open(args.out, encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


# ----------------------------------------------------- 建号


def test_stage_accounts_carry_stage_and_language(session, tmp_path):
    zh = create(session, tmp_path, stage=1, language="zh", count=2)
    en = create(session, tmp_path, stage=1, language="en", count=3)
    assert [r["annotator_id"] for r in zh] == ["P1-ZH-01", "P1-ZH-02"]
    assert [r["annotator_id"] for r in en] == ["P1-EN-01", "P1-EN-02", "P1-EN-03"]
    stored = {a.annotator_id: (a.phase, a.language) for a in session.query(Annotator)}
    assert stored["P1-ZH-02"] == ("main", "zh")
    assert stored["P1-EN-03"] == ("main", "en")


def test_numbers_are_never_reused(session, tmp_path):
    """号只发不收：补招的人接着最大号往后编，哪怕中间有人退出后被停用。"""
    add(session, "P1-EN-01", "en")
    add(session, "P1-EN-02", "en", active=False)
    rows = create(session, tmp_path, stage=1, language="en", count=1)
    assert rows[0]["annotator_id"] == "P1-EN-03"


def test_numbering_is_per_stage_and_language(session, tmp_path):
    add(session, "P1-EN-05", "en")
    assert create(session, tmp_path, stage=1, language="zh")[0]["annotator_id"] == "P1-ZH-01"
    assert create(session, tmp_path, stage=2, language="en")[0]["annotator_id"] == "P2-EN-01"


def test_stage_format_is_reserved_for_stage_accounts(session, tmp_path):
    """用 --prefix 手拼 P1-ZH 会绕过语言与 phase 的绑定，直接拒绝。"""
    with pytest.raises(SystemExit):
        create(session, tmp_path, prefix="P1-ZH", phase="main", language="en")


def test_other_accounts_still_need_prefix_and_phase(session, tmp_path):
    with pytest.raises(SystemExit):
        create(session, tmp_path, prefix="DEMO", language="en")
    rows = create(session, tmp_path, prefix="DEMO", phase="training", language="en")
    assert rows[0]["annotator_id"] == "DEMO-01"


# ----------------------------------------------------- 取人


def test_plan_takes_only_active_main_accounts_of_that_stage(session):
    add(session, "P1-ZH-01", "zh")
    add(session, "P1-EN-01", "en")
    add(session, "P1-EN-02", "en", active=False)
    add(session, "P2-EN-01", "en")
    add(session, "TRZH-01", "zh", phase="training")
    assert manage.stage_annotators(session, 1) == {"P1-EN-01": "en", "P1-ZH-01": "zh"}


def test_plan_refuses_an_id_whose_language_disagrees(session):
    """编号写着 ZH、库里却是 en：分配不知道该信哪个，宁可停下。"""
    add(session, "P1-ZH-01", "en")
    with pytest.raises(SystemExit):
        manage.stage_annotators(session, 1)


def test_set_language_cannot_contradict_the_id(session):
    add(session, "P1-EN-01", "en")
    args = SimpleNamespace(annotator_id="P1-EN-01", language="zh")
    with patch("manage.session_factory", return_value=lambda: session):
        with pytest.raises(SystemExit):
            manage.cmd_set_language(args)
    assert session.get(Annotator, "P1-EN-01").language == "en"


# ----------------------------------------------------- 中文专属子任务


def test_zh_only_is_chsims_text_and_full():
    got = manage.zh_only_subtasks(["chsims_a_1", "meld_dia1_utt0"])
    assert got == {("chsims_a_1", "text"), ("chsims_a_1", "audiovisual")}


# ----------------------------------------------------- 训练分配


def seed_templates(session):
    from app.models import Assignment, Task

    for task_id in ("T-zh-1", "T-zh-2", "T-en-1"):
        session.add(Task(task_id=task_id, media_id=task_id, source_id=task_id,
                         title=task_id, modality="face", src="/x", duration=1.0))
    add(session, "TRZH-01", "zh", phase="training")
    add(session, "TREN-01", "en", phase="training")
    session.flush()
    for annotator_id, task_id, order in [("TRZH-01", "T-zh-2", 0), ("TRZH-01", "T-zh-1", 1),
                                         ("TREN-01", "T-en-1", 0)]:
        session.add(Assignment(annotator_id=annotator_id, task_id=task_id,
                               phase="training", order_index=order))
    session.commit()


def training_queue(session, annotator_id):
    from app.models import Assignment

    rows = session.query(Assignment).filter_by(annotator_id=annotator_id, phase="training")
    return [r.task_id for r in rows.order_by(Assignment.order_index)]


def run_assign_training(session, stage=1):
    args = SimpleNamespace(stage=stage, template_zh="TRZH-01", template_en="TREN-01")
    with patch("manage.session_factory", return_value=lambda: session):
        manage.cmd_assign_training(args)


def test_training_is_copied_by_language_in_template_order(session):
    seed_templates(session)
    add(session, "P1-ZH-01", "zh")
    add(session, "P1-EN-01", "en")
    run_assign_training(session)
    assert training_queue(session, "P1-ZH-01") == ["T-zh-2", "T-zh-1"]
    assert training_queue(session, "P1-EN-01") == ["T-en-1"]


def test_training_already_assigned_is_left_alone(session):
    """训练可能已经开始，重挂会打乱他的队列：跑第二遍不能重复插入。"""
    seed_templates(session)
    add(session, "P1-ZH-01", "zh")
    run_assign_training(session)
    run_assign_training(session)
    assert training_queue(session, "P1-ZH-01") == ["T-zh-2", "T-zh-1"]
