from fastapi import FastAPI

from .config import Settings, load_settings
from .db import create_db_engine, create_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="XMER Annotation API", version="2.0.0")

    engine = create_db_engine(settings.database_url)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": app.version}

    return app


app = create_app()
