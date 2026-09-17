import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
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

    @app.exception_handler(RequestValidationError)
    async def _log_validation_error(request: Request, exc: RequestValidationError):
        """把 422 的原因写进日志。

        默认的 422 只把详情放在响应体里，客户端往往只看状态码。线上一旦
        出现校验失败，服务器日志里只有一行 `422 Unprocessable Entity`，
        查不出是哪个字段——而这种失败会被客户端的重试队列无限放大。

        只记字段路径与错误类型，不记值：请求体里有标注内容。
        """
        where = [
            {"loc": ".".join(str(p) for p in e["loc"]), "type": e["type"]}
            for e in exc.errors()
        ]
        logging.getLogger("xmer.validation").warning(
            "422 %s %s → %s", request.method, request.url.path, where
        )
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": app.version}

    return app

# 不在模块层构造 app：那会让导入本模块就读环境变量。
# 生产入口为 `uvicorn app.main:create_app --factory`。
