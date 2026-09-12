from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.adapters.inbound.http.dependencies import (
    PageLimit,
    PageOffset,
    ProductServiceDependency,
)
from app.domain.products import ProductNotFound

router = APIRouter(prefix="/products", tags=["products"])


class ProductOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    sku: str
    description: str | None
    price: Decimal
    is_active: bool
    ean: str | None
    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    stock: list["StockOutput"] = Field(default_factory=list)


class StockOutput(BaseModel):
    warehouse_id: int
    warehouse_name: str
    on_hand: int
    reserved: int
    available: int


@router.get("", response_model=list[ProductOutput])
async def list_products(
    service: ProductServiceDependency,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
    q: Annotated[str | None, Query(max_length=255)] = None,
    is_active: bool | None = None,
):
    return await service.list(limit, offset, q, is_active)


@router.get("/{product_id}", response_model=ProductOutput)
async def get_product(product_id: int, service: ProductServiceDependency):
    try:
        return await service.get(product_id)
    except ProductNotFound as error:
        raise HTTPException(status_code=404, detail="Product not found.") from error
