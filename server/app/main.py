from fastapi import FastAPI
from sqlalchemy import Engine

from .admin import router as admin_router
from .api import router
from .config import Settings, load_settings
from .db import create_db_engine, create_session_factory


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="XMER Annotation API", version="2.0.0")

    engine = engine or create_db_engine(settings.database_url)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.include_router(router)
    app.include_router(admin_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": app.version}

    return app

# 不在模块层构造 app：那会让导入本模块就读环境变量。
# 生产入口为 `uvicorn app.main:create_app --factory`。
