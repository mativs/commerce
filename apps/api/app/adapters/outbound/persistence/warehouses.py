from __future__ import annotations

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.persistence.models import Product, Stock, Warehouse
from app.domain.warehouses import (
    StockFilter,
    WarehouseNotFound,
    WarehouseProductView,
    WarehouseView,
)


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

    async def products(
        self, warehouse_id: int, stock: StockFilter, limit: int, offset: int
    ) -> list[WarehouseProductView]:
        async with self.session.begin():
            exists = await self.session.scalar(
                select(Warehouse.id).where(
                    Warehouse.id == warehouse_id, Warehouse.deleted_at.is_(None)
                )
            )
            if exists is None:
                raise WarehouseNotFound
            on_hand = func.coalesce(Stock.on_hand, 0)
            booked = func.coalesce(Stock.reserved, 0)
            available = on_hand - booked
            query = (
                select(Product.id, Product.name, Product.sku, on_hand, booked, available)
                .outerjoin(
                    Stock,
                    and_(Stock.product_id == Product.id, Stock.warehouse_id == warehouse_id),
                )
                .where(Product.deleted_at.is_(None))
                .order_by(Product.name, Product.id)
                .limit(limit)
                .offset(offset)
            )
            if stock == "available":
                query = query.where(available > 0)
            elif stock == "on_hand":
                query = query.where(on_hand > 0)
            rows = (await self.session.execute(query)).all()
            return [WarehouseProductView(*row) for row in rows]
