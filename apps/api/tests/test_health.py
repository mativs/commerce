from fastapi.testclient import TestClient

from app.infrastructure.config import Settings
from app.main import create_app


def test_health() -> None:
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        database_url="postgresql+asyncpg://test:test@localhost/test",
        cors_origins=["http://localhost:5173"],
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/health", headers={"Origin": "http://localhost:5173"})
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert (
            "access-control-allow-origin"
            not in client.get("/health", headers={"Origin": "https://untrusted.example"}).headers
        )
