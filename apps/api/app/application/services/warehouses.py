from app.application.ports.warehouses import WarehouseRepository
from app.domain.warehouses import WarehouseView


class WarehouseService:
    def __init__(self, repository: WarehouseRepository):
        self.repository = repository

    async def list(self, limit: int, offset: int) -> list[WarehouseView]:
        return await self.repository.list(limit, offset)

    async def get(self, warehouse_id: int) -> WarehouseView:
        return await self.repository.get(warehouse_id)
