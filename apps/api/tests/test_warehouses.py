import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def test_warehouse_crud(warehouse_client):
    client, _ = warehouse_client
    assert client.get("/warehouses").json() == []
    data = {"name": "  Main warehouse  ", "latitude": -90, "longitude": 180}
    response = client.post("/warehouses", json=data)
    assert response.status_code == 201
    warehouse = response.json()
    assert warehouse.items() >= {**data, "name": "Main warehouse"}.items()
    assert warehouse["created_at"] and warehouse["updated_at"]
    assert warehouse["deleted_at"] is None
    url = response.headers["location"]
    assert client.get(url).json() == warehouse
    assert client.get("/warehouses").json() == [warehouse]
    updated = {"name": "North", "latitude": 90, "longitude": -180}
    assert client.put(url, json=updated).json().items() >= updated.items()
    assert client.get(url).json().items() >= updated.items()
    response = client.delete(url)
    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/warehouses").json() == []
    assert client.get(url).status_code == 404
    assert client.put(url, json=updated).status_code == 404
    assert client.delete(url).status_code == 404
    logs = client.get(f"{url}/logs").json()
    assert [log["action"] for log in logs] == ["create", "update", "delete"]
    assert logs[1]["old_values"]["name"] == "Main warehouse"
    assert logs[1]["new_values"]["name"] == "North"
    assert logs[2]["new_values"]["deleted_at"] is not None
    assert logs[1]["new_values"]["created_at"] == logs[0]["new_values"]["created_at"]
    assert logs[1]["new_values"]["updated_at"] != logs[0]["new_values"]["updated_at"]


@pytest.mark.parametrize(
    "invalid",
    [
        {"name": " "},
        {"name": "x" * 256},
        {"latitude": -90.01},
        {"latitude": 90.01},
        {"longitude": -180.01},
        {"longitude": 180.01},
        {"latitude": None},
        {"longitude": "NaN"},
    ],
)
def test_validation(warehouse_client, invalid):
    client, _ = warehouse_client
    valid = {"name": "Main", "latitude": 0, "longitude": 0}
    created = client.post("/warehouses", json=valid)
    url = created.headers["location"]
    assert client.post("/warehouses", json={**valid, **invalid}).status_code == 422
    assert client.put(url, json={**valid, **invalid}).status_code == 422
    assert client.get(url).json() == created.json()
    assert client.post("/warehouses", json={"name": "Missing coordinates"}).status_code == 422


def test_postgres_constraints_and_types(warehouse_client):
    _, sessions = warehouse_client

    async def check():
        async with sessions() as session:
            columns = (
                (
                    await session.execute(
                        text(
                            "SELECT data_type FROM information_schema.columns "
                            "WHERE table_schema = current_schema() AND table_name = 'warehouses' "
                            "AND column_name IN ('latitude', 'longitude')"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert columns == ["double precision", "double precision"]
        for latitude, longitude in [(-91, 0), (91, 0), (0, -181), (0, 181), (None, 0), (0, None)]:
            async with sessions() as session:
                with pytest.raises(IntegrityError):
                    await session.execute(
                        text(
                            "INSERT INTO warehouses (name, latitude, longitude) "
                            "VALUES ('Invalid', :latitude, :longitude)"
                        ),
                        {"latitude": latitude, "longitude": longitude},
                    )
                await session.rollback()

    asyncio.run(check())
