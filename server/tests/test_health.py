from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_health_reports_ok():
    app = create_app(Settings(database_url="sqlite+pysqlite:///:memory:", admin_token=""))
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
