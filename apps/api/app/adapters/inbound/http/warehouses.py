from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.adapters.inbound.http.dependencies import DatabaseSession, PageLimit, PageOffset
from app.adapters.outbound.persistence.models import Warehouse

router = APIRouter(prefix="/warehouses", tags=["warehouses"])


class WarehouseInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=255)


class WarehouseOutput(WarehouseInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


async def find_warehouse(session: DatabaseSession, warehouse_id: int) -> Warehouse:
    warehouse = await session.get(Warehouse, warehouse_id)
    if warehouse is None or warehouse.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Warehouse not found.")
    return warehouse


@router.get("", response_model=list[WarehouseOutput])
async def list_warehouses(session: DatabaseSession, limit: PageLimit = 50, offset: PageOffset = 0):
    return (
        await session.scalars(
            select(Warehouse)
            .where(Warehouse.deleted_at.is_(None))
            .order_by(Warehouse.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()


@router.get("/{warehouse_id}", response_model=WarehouseOutput)
async def get_warehouse(warehouse_id: int, session: DatabaseSession):
    return await find_warehouse(session, warehouse_id)
