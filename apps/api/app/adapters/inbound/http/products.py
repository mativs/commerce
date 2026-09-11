from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.adapters.inbound.http.dependencies import DatabaseSession
from app.adapters.inbound.http.warehouses import AuditLogOutput
from app.adapters.outbound.identifiers.ean import random_ean
from app.adapters.outbound.persistence.models import AuditLog, Product
from app.domain.product import validate_ean

router = APIRouter(prefix="/products", tags=["products"])


class ProductInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    sku: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2, allow_inf_nan=False)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    is_active: bool = Field(default=True, strict=True)

    @field_validator("sku", "currency", mode="before")
    @classmethod
    def uppercase(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("description")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        return value or None


class ProductOutput(ProductInput):
    model_config = ConfigDict(from_attributes=True)

    ean: str | None

    @field_validator("ean")
    @classmethod
    def check_ean(cls, value: str | None) -> str | None:
        return validate_ean(value) if value is not None else None

    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


async def find_product(session: DatabaseSession, product_id: int) -> Product:
    product = await session.get(Product, product_id)
    if product is None or product.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Product not found.")
    return product


def raise_identifier_conflict(error: IntegrityError) -> None:
    # asyncpg's original PostgreSQL error retains the violated constraint name.
    cause = error.orig.__cause__
    constraint = getattr(cause, "constraint_name", None)
    field = {"uq_products_sku": "SKU", "uq_products_ean": "EAN"}.get(constraint)
    if field is None:
        raise error
    raise HTTPException(
        status_code=409,
        detail=f"{field} is already used by another product, including deleted products.",
    ) from error


@router.get("", response_model=list[ProductOutput])
async def list_products(session: DatabaseSession):
    return (
        await session.scalars(
            select(Product).where(Product.deleted_at.is_(None)).order_by(Product.id)
        )
    ).all()


@router.post("", response_model=ProductOutput, status_code=status.HTTP_201_CREATED)
async def create_product(data: ProductInput, session: DatabaseSession, response: Response):
    for _ in range(5):
        try:
            async with session.begin():
                product = Product(**data.model_dump(), ean=random_ean())
                session.add(product)
                await session.flush()
        except IntegrityError as error:
            if getattr(error.orig.__cause__, "constraint_name", None) == "uq_products_ean":
                # Rollback includes the audit entry; retry against the database constraint
                # so concurrent inserts and identifiers on deleted rows are covered too.
                continue
            raise_identifier_conflict(error)
        response.headers["Location"] = f"/products/{product.id}"
        return product
    raise HTTPException(
        status_code=503, detail="Could not generate a unique EAN. Please try again."
    )


@router.get("/{product_id}", response_model=ProductOutput)
async def get_product(product_id: int, session: DatabaseSession):
    return await find_product(session, product_id)


@router.put("/{product_id}", response_model=ProductOutput)
async def update_product(product_id: int, data: ProductInput, session: DatabaseSession):
    try:
        async with session.begin():
            product = await find_product(session, product_id)
            for name, value in data.model_dump().items():
                setattr(product, name, value)
            await session.flush()
            await session.refresh(product)
    except IntegrityError as error:
        raise_identifier_conflict(error)
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(product_id: int, session: DatabaseSession):
    async with session.begin():
        product = await find_product(session, product_id)
        product.deleted_at = datetime.now(UTC)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{product_id}/logs", response_model=list[AuditLogOutput])
async def product_logs(product_id: int, session: DatabaseSession):
    if await session.get(Product, product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    return (
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.table_name == "products", AuditLog.record_id == product_id)
            .order_by(AuditLog.id)
        )
    ).all()
