from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.outbound.persistence.orders import SqlAlchemyOrderRepository
from app.adapters.outbound.persistence.products import SqlAlchemyProductRepository
from app.adapters.outbound.persistence.warehouses import SqlAlchemyWarehouseRepository
from app.application.services.orders import OrderService
from app.application.services.products import ProductService
from app.application.services.warehouses import WarehouseService
from app.infrastructure.order_simulation import SimulatedOrderService


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_maker: async_sessionmaker[AsyncSession] = request.app.state.session_maker
    async with session_maker() as session:
        yield session


DatabaseSession = Annotated[AsyncSession, Depends(get_session)]


def order_service(request: Request, session: DatabaseSession) -> OrderService:
    return SimulatedOrderService(
        SqlAlchemyOrderRepository(session),
        request.app.state.order_geocoder,
        request.app.state.payment_gateway,
    )


def product_service(session: DatabaseSession) -> ProductService:
    return ProductService(SqlAlchemyProductRepository(session))


def warehouse_service(session: DatabaseSession) -> WarehouseService:
    return WarehouseService(SqlAlchemyWarehouseRepository(session))


OrderServiceDependency = Annotated[OrderService, Depends(order_service)]
ProductServiceDependency = Annotated[ProductService, Depends(product_service)]
WarehouseServiceDependency = Annotated[WarehouseService, Depends(warehouse_service)]


# Shared bounds for all collection endpoints; keep array response bodies compatible.

PageLimit = Annotated[int, Query(ge=1, le=100)]
PageOffset = Annotated[int, Query(ge=0)]
