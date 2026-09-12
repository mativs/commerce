from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select, text

from app.adapters.inbound.http.dependencies import DatabaseSession, PageLimit, PageOffset
from app.adapters.outbound.persistence.models import Product, Stock, Warehouse

router = APIRouter(prefix="/products", tags=["products"])


class ProductOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    sku: str
    description: str | None
    price: Decimal
    currency: str
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


async def product_output(session: DatabaseSession, product: Product) -> ProductOutput:
    stock_exists = await session.scalar(text("SELECT to_regclass(current_schema() || '.stock')"))
    if stock_exists is None:
        rows = []
    else:
        rows = (
            await session.execute(
                select(Stock, Warehouse.name)
                .join(Warehouse, Warehouse.id == Stock.warehouse_id)
                .where(
                    Stock.product_id == product.id,
                    Stock.deleted_at.is_(None),
                    Warehouse.deleted_at.is_(None),
                )
                .order_by(Warehouse.id)
            )
        ).all()
    output = ProductOutput.model_validate(product)
    output.stock = [
        StockOutput(
            warehouse_id=stock.warehouse_id,
            warehouse_name=warehouse_name,
            on_hand=stock.on_hand,
            reserved=stock.reserved,
            available=stock.on_hand - stock.reserved,
        )
        for stock, warehouse_name in rows
    ]
    return output


async def find_product(session: DatabaseSession, product_id: int) -> Product:
    product = await session.get(Product, product_id)
    if product is None or product.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Product not found.")
    return product


@router.get("", response_model=list[ProductOutput])
async def list_products(
    session: DatabaseSession,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
    q: Annotated[str | None, Query(max_length=255)] = None,
    is_active: bool | None = None,
    currency: Annotated[str | None, Query(pattern=r"^[A-Z]{3}$")] = None,
):
    query = select(Product).where(Product.deleted_at.is_(None))
    if q and q.strip():
        query = query.where(
            or_(
                Product.name.icontains(q.strip(), autoescape=True),
                Product.sku.icontains(q.strip(), autoescape=True),
            )
        )
    if is_active is not None:
        query = query.where(Product.is_active == is_active)
    if currency is not None:
        query = query.where(Product.currency == currency)
    products = (await session.scalars(query.order_by(Product.id).limit(limit).offset(offset))).all()
    return [await product_output(session, product) for product in products]


@router.get("/{product_id}", response_model=ProductOutput)
async def get_product(product_id: int, session: DatabaseSession):
    return await product_output(session, await find_product(session, product_id))
