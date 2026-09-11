import pytest

from app.config import load_settings


def test_missing_database_url_fails_loudly(monkeypatch):
    """缺配置时必须起不来。

    回归：部署时发现 compose 少带 --env-file 会让变量为空，而旧的缺省值会让服务
    静默回落到本地 SQLite——标注数据写进容器里一个没人会去看的文件，且表面无异常。
    """
    monkeypatch.delenv("XMER_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="XMER_DATABASE_URL"):
        load_settings()


def test_database_url_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("XMER_DATABASE_URL", "postgresql+psycopg://u:p@h/db")
    monkeypatch.setenv("XMER_ADMIN_TOKEN", "secret")
    settings = load_settings()
    assert settings.database_url == "postgresql+psycopg://u:p@h/db"
    assert settings.admin_token == "secret"
