from typing import Protocol

from app.domain.warehouses import WarehouseView


class WarehouseRepository(Protocol):
    async def list(self, limit: int, offset: int) -> list[WarehouseView]: ...

    async def get(self, warehouse_id: int) -> WarehouseView: ...
