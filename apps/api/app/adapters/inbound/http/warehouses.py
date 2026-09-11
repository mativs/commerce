from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.adapters.inbound.http.dependencies import DatabaseSession
from app.adapters.outbound.persistence.models import AuditLog, Warehouse

router = APIRouter(prefix="/warehouses", tags=["warehouses"])


class WarehouseInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


class WarehouseOutput(WarehouseInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


async def find_warehouse(session: DatabaseSession, warehouse_id: int) -> Warehouse:
    warehouse = await session.get(Warehouse, warehouse_id)
    if warehouse is None or warehouse.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Warehouse not found.")
    return warehouse


@router.get("", response_model=list[WarehouseOutput])
async def list_warehouses(session: DatabaseSession):
    return (
        await session.scalars(
            select(Warehouse).where(Warehouse.deleted_at.is_(None)).order_by(Warehouse.id)
        )
    ).all()


@router.post("", response_model=WarehouseOutput, status_code=status.HTTP_201_CREATED)
async def create_warehouse(data: WarehouseInput, session: DatabaseSession, response: Response):
    async with session.begin():
        warehouse = Warehouse(**data.model_dump())
        session.add(warehouse)
        await session.flush()
    response.headers["Location"] = f"/warehouses/{warehouse.id}"
    return warehouse


@router.get("/{warehouse_id}", response_model=WarehouseOutput)
async def get_warehouse(warehouse_id: int, session: DatabaseSession):
    return await find_warehouse(session, warehouse_id)


@router.put("/{warehouse_id}", response_model=WarehouseOutput)
async def update_warehouse(warehouse_id: int, data: WarehouseInput, session: DatabaseSession):
    async with session.begin():
        warehouse = await find_warehouse(session, warehouse_id)
        for field, value in data.model_dump().items():
            setattr(warehouse, field, value)
        await session.flush()
        await session.refresh(warehouse)
    return warehouse


@router.delete("/{warehouse_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_warehouse(warehouse_id: int, session: DatabaseSession):
    async with session.begin():
        warehouse = await find_warehouse(session, warehouse_id)
        warehouse.deleted_at = datetime.now(UTC)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class AuditLogOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    record_id: int
    action: str
    old_values: dict | None
    new_values: dict | None
    created_at: datetime


@router.get("/{warehouse_id}/logs", response_model=list[AuditLogOutput])
async def warehouse_logs(warehouse_id: int, session: DatabaseSession):
    # History remains available after soft deletion.
    if await session.get(Warehouse, warehouse_id) is None:
        raise HTTPException(status_code=404, detail="Warehouse not found.")
    return (
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.table_name == "warehouses", AuditLog.record_id == warehouse_id)
            .order_by(AuditLog.id)
        )
    ).all()
