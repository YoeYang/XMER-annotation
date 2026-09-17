"""导入任务清单时，编号只补不改。

V3 的清单里 `task_id` / `media_id` / `src` 全用编号写成，编号本身也随清单
一起进库。要是导入时把 `display_id` 留空，之后跑 `assign-display-ids`
会把这些样本当成没编号而重新发号——`task_id` 写着 S0123、编号却成了 S0456，
标注结果从此对不上样本。这批测试把这条路堵死。
"""
import json

import pytest
from sqlalchemy.orm import Session

import manage
from app.models import Task


def manifest(task_id="S0001::face", **kw):
    item = {
        "task_id": task_id,
        "media_id": "S0001-face",
        "source_id": "meld_dia17_utt6",
        "display_id": "S0001",
        "title": "meld_dia17_utt6 · 仅面部",
        "modality": "face",
        "src": "/pool/v3/media/S0001/face.mp4",
        "duration": 4.0,
    }
    item.update(kw)
    return [item]


@pytest.fixture
def importer(session: Session, monkeypatch, tmp_path):
    """让 manage.py 的导入命令走测试用的会话。"""
    monkeypatch.setattr(manage, "session_factory", lambda: lambda: _Ctx(session))

    def run(payload):
        path = tmp_path / "tasks.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        manage.cmd_import_tasks(_Args(str(path)))

    return run


class _Args:
    def __init__(self, file):
        self.file = file


class _Ctx:
    """把既有会话包成上下文管理器，退出时不关闭——测试还要接着查。"""

    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *exc):
        return False


def test_display_id_comes_in_with_the_manifest(session: Session, importer):
    importer(manifest())
    assert session.get(Task, "S0001::face").display_id == "S0001"


def test_existing_number_is_never_overwritten(session: Session, importer):
    """清单没带编号时，库里已有的要原样留着，不能被清空。"""
    importer(manifest())
    importer(manifest(title="改过的标题", display_id=None))

    row = session.get(Task, "S0001::face")
    assert row.display_id == "S0001"
    assert row.title == "改过的标题", "其他字段照常更新"


def test_conflicting_number_stops_the_import(session: Session, importer):
    """库里和清单各说一个编号，只能停下来查清楚——猜哪边对都会错。"""
    importer(manifest())
    with pytest.raises(SystemExit) as caught:
        importer(manifest(display_id="S0456", media_id="S0456-face"))
    assert "编号冲突" in str(caught.value)


def test_manifest_without_numbers_still_imports(session: Session, importer):
    """老格式的清单（不带编号）照样能导，编号留给 assign-display-ids 去发。"""
    item = manifest(task_id="legacy::face")[0]
    del item["display_id"]
    importer([item])
    assert session.get(Task, "legacy::face").display_id is None
