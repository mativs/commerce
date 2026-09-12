from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.adapters.inbound.http.dependencies import DatabaseSession, PageLimit, PageOffset
from app.adapters.inbound.http.shipping_addresses import ShippingAddressInput
from app.adapters.outbound.persistence.orders import SqlAlchemyOrderRepository
from app.application.services.orders import OrderService
from app.domain.order import (
    CreateOrder,
    IdempotencyConflict,
    InvalidOrder,
    OrderNotFound,
    RequestedItem,
)
from app.domain.shipping_address import AddressDetails

router = APIRouter(prefix="/orders", tags=["orders"])


class ItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: int = Field(gt=0, le=2147483647, strict=True)
    quantity: int = Field(gt=0, le=2147483647, strict=True)


class OrderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    shipping_address: ShippingAddressInput
    items: list[ItemInput] = Field(min_length=1, max_length=1000)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def combine_items(self):
        quantities: dict[int, int] = {}
        for item in self.items:
            quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity
        self.items = [
            ItemInput(product_id=pid, quantity=qty) for pid, qty in sorted(quantities.items())
        ]
        return self


class ItemOutput(BaseModel):
    product_id: int
    quantity: int
    unit_price: Decimal


class HistoryOutput(BaseModel):
    status: str
    reason: str | None
    created_at: datetime


class OrderOutput(BaseModel):
    id: int
    status: Literal["CREATED", "BOOKED", "PAID", "CANCELLED"]
    shipping_address: dict
    latitude: float | None
    longitude: float | None
    warehouse_id: int | None
    total_amount: Decimal
    notes: str | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime
    items: list[ItemOutput]
    history: list[HistoryOutput]


def order_service(request: Request, session: DatabaseSession) -> OrderService:
    return OrderService(
        SqlAlchemyOrderRepository(session),
        request.app.state.order_geocoder,
        request.app.state.payment_gateway,
    )


Service = Annotated[OrderService, Depends(order_service)]


@router.post(
    "",
    response_model=OrderOutput,
    status_code=201,
    responses={
        202: {"description": "Order is still processing or awaiting reconciliation"},
        409: {"description": "Idempotency key reused with different input"},
    },
)
async def create_order(
    data: OrderInput,
    service: Service,
    response: Response,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=128, pattern=r"^[!-~]+$")],
):
    command = CreateOrder(
        shipping_address=AddressDetails(**data.shipping_address.model_dump()),
        items=tuple(RequestedItem(i.product_id, i.quantity) for i in data.items),
        notes=data.notes,
    )
    try:
        order = await service.create(command, idempotency_key)
    except InvalidOrder as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except IdempotencyConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    response.headers["Location"] = f"/orders/{order.id}"
    if order.status in ("CREATED", "BOOKED"):
        response.status_code = 202
    return asdict(order)


@router.get("", response_model=list[OrderOutput])
async def list_orders(
    service: Service,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
):
    return [asdict(order) for order in await service.repository.list(limit, offset)]


@router.get("/{order_id}", response_model=OrderOutput)
async def get_order(order_id: int, service: Service):
    try:
        return asdict(await service.repository.get(order_id))
    except OrderNotFound as error:
        raise HTTPException(status_code=404, detail="Order not found.") from error
