from __future__ import annotations

from typing import Protocol

from app.domain.warehouses import StockFilter, WarehouseProductView, WarehouseView


class WarehouseRepository(Protocol):
    async def list(self, limit: int, offset: int) -> list[WarehouseView]: ...

    async def get(self, warehouse_id: int) -> WarehouseView: ...

    async def products(
        self, warehouse_id: int, stock: StockFilter, limit: int, offset: int
    ) -> list[WarehouseProductView]: ...
