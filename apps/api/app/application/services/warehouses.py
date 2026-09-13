from __future__ import annotations

from app.application.ports.warehouses import WarehouseRepository
from app.domain.warehouses import StockFilter, WarehouseProductView, WarehouseView


class WarehouseService:
    def __init__(self, repository: WarehouseRepository):
        self.repository = repository

    async def list(self, limit: int, offset: int) -> list[WarehouseView]:
        return await self.repository.list(limit, offset)

    async def get(self, warehouse_id: int) -> WarehouseView:
        return await self.repository.get(warehouse_id)

    async def products(
        self, warehouse_id: int, stock: StockFilter, limit: int, offset: int
    ) -> list[WarehouseProductView]:
        return await self.repository.products(warehouse_id, stock, limit, offset)
