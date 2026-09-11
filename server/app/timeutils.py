from datetime import datetime, timezone
from typing import Annotated

from pydantic import PlainSerializer


def to_utc_iso(value: datetime) -> str:
    """统一输出带时区的 UTC ISO-8601。

    naive datetime 一律按 UTC 解释：库里存的本就是 UTC，只是部分驱动
    （如 SQLite）读回时丢掉了 tzinfo。接口对外不能出现无时区的时间戳，
    否则客户端只能靠猜。
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


UtcDateTime = Annotated[datetime, PlainSerializer(to_utc_iso, return_type=str)]
