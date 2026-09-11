import hashlib
import secrets
from collections.abc import Iterator

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Annotator


def new_token() -> str:
    """生成标注者专属网址里的 token。"""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    # token 由 secrets 生成，熵足够高，不需要 bcrypt 这类针对弱口令的慢哈希
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def current_annotator(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> Annotator:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "缺少访问令牌。请使用分配给你的专属网址打开标注页面。",
        )
    token = authorization.removeprefix("Bearer ").strip()
    annotator = session.scalar(
        select(Annotator).where(Annotator.token_hash == hash_token(token))
    )
    if annotator is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "访问令牌无效。请向研究者索取新的专属网址。"
        )
    if not annotator.active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "该账号已停用。请联系研究者。")
    return annotator
