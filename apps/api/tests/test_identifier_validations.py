from fastapi.testclient import TestClient

from app.infrastructure.config import Settings
from app.main import create_app


def test_oversized_product_id_is_rejected_before_database_access():
    app = create_app(
        Settings(database_url="postgresql+asyncpg://user:pass@localhost/db")  # pyright: ignore[reportArgumentType]
    )

    with TestClient(app) as client:
        response = client.get("/products/2147483648")

    assert response.status_code == 422
