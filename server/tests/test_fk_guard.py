"""外键校验必须真的开着。

`conftest` 里的外键 listener 曾挂在 SQLAlchemy 的 `Engine` 基类上——全局副作用，
连迁移用的引擎一起强开。收窄到应用测试引擎之后，这条测试确保收窄没收过头：
外键校验在应用测试里依然生效，否则一大批引用完整性测试会静默变成空转。
"""
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Assignment


def test_foreign_keys_are_still_enforced(session: Session):
    session.add(
        Assignment(
            annotator_id="nobody", task_id="nothing", phase="main", order_index=0
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
