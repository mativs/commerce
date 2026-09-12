from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.adapters.inbound.http.dependencies import (
    PageLimit,
    PageOffset,
    WarehouseServiceDependency,
)
from app.domain.warehouses import WarehouseNotFound

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


@router.get("", response_model=list[WarehouseOutput])
async def list_warehouses(
    service: WarehouseServiceDependency, limit: PageLimit = 50, offset: PageOffset = 0
):
    return await service.list(limit, offset)


@router.get("/{warehouse_id}", response_model=WarehouseOutput)
async def get_warehouse(warehouse_id: int, service: WarehouseServiceDependency):
    try:
        return await service.get(warehouse_id)
    except WarehouseNotFound as error:
        raise HTTPException(status_code=404, detail="Warehouse not found.") from error
