import asyncio

from app.adapters.outbound.persistence.models import Warehouse


def test_warehouses_are_read_only(warehouse_client):
    client, sessions = warehouse_client

    async def seed():
        async with sessions() as session, session.begin():
            warehouse = Warehouse(name="Main", latitude=-38, longitude=-57)
            session.add(warehouse)
            await session.flush()
            return warehouse.id

    warehouse_id = asyncio.run(seed())
    warehouse = client.get("/warehouses").json()
    assert len(warehouse) == 1 and warehouse[0]["id"] == warehouse_id
    assert client.get(f"/warehouses/{warehouse_id}").json() == warehouse[0]
