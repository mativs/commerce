from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select

from app.adapters.inbound.http.dependencies import DatabaseSession, PageLimit, PageOffset
from app.adapters.outbound.persistence.models import Product, Stock, Warehouse

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


def _product_output(product: Product, rows: Sequence[tuple[Stock, str]]) -> ProductOutput:
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


async def _products_with_stock(
    session: DatabaseSession, query, limit: int, offset: int
) -> Sequence[tuple[Product, Stock | None, str | None]]:
    # Apply pagination before the joins so one product is never pushed to a
    # different page by having balances in multiple warehouses.
    page = query.order_by(Product.id).limit(limit).offset(offset).subquery("product_page")
    statement = (
        select(Product, Stock, Warehouse.name)
        .join(page, Product.id == page.c.id)
        .outerjoin(
            Stock,
            and_(
                Stock.product_id == Product.id,
            ),
        )
        .outerjoin(
            Warehouse,
            and_(
                Warehouse.id == Stock.warehouse_id,
                Warehouse.deleted_at.is_(None),
            ),
        )
        .order_by(Product.id, Warehouse.id)
    )
    return (await session.execute(statement)).tuples().all()


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
    rows = await _products_with_stock(session, query, limit, offset)
    grouped: dict[int, tuple[Product, list[tuple[Stock, str]]]] = {}
    for product, stock, warehouse_name in rows:
        entry = grouped.setdefault(product.id, (product, []))
        if stock is not None and warehouse_name is not None:
            entry[1].append((stock, warehouse_name))
    return [_product_output(product, stock_rows) for product, stock_rows in grouped.values()]


@router.get("/{product_id}", response_model=ProductOutput)
async def get_product(product_id: int, session: DatabaseSession):
    product = await find_product(session, product_id)
    rows = (
        (
            await session.execute(
                select(Stock, Warehouse.name)
                .join(Warehouse, Warehouse.id == Stock.warehouse_id)
                .where(
                    Stock.product_id == product.id,
                    Warehouse.deleted_at.is_(None),
                )
                .order_by(Warehouse.id)
            )
        )
        .tuples()
        .all()
    )
    return _product_output(product, rows)
