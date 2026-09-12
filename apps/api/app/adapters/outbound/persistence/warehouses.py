from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.persistence.models import Warehouse
from app.domain.warehouses import WarehouseNotFound, WarehouseView


class SqlAlchemyWarehouseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _view(warehouse: Warehouse) -> WarehouseView:
        return WarehouseView(
            id=warehouse.id,
            name=warehouse.name,
            latitude=warehouse.latitude,
            longitude=warehouse.longitude,
            created_at=warehouse.created_at,
            updated_at=warehouse.updated_at,
            deleted_at=warehouse.deleted_at,
        )

    async def list(self, limit: int, offset: int) -> list[WarehouseView]:
        async with self.session.begin():
            warehouses = await self.session.scalars(
                select(Warehouse)
                .where(Warehouse.deleted_at.is_(None))
                .order_by(Warehouse.id)
                .limit(limit)
                .offset(offset)
            )
            return [self._view(warehouse) for warehouse in warehouses]

    async def get(self, warehouse_id: int) -> WarehouseView:
        async with self.session.begin():
            warehouse = await self.session.scalar(
                select(Warehouse).where(
                    Warehouse.id == warehouse_id,
                    Warehouse.deleted_at.is_(None),
                )
            )
            if warehouse is None:
                raise WarehouseNotFound
            return self._view(warehouse)
