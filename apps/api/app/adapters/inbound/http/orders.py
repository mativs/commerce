from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.adapters.inbound.http.dependencies import (
    BoundedId,
    OrderServiceDependency,
    PageLimit,
    PageOffset,
)
from app.domain.order import (
    CreateOrder,
    CustomerDetails,
    IdempotencyConflict,
    InvalidOrder,
    OrderNotFound,
    PaymentDetails,
    RequestedItem,
)
from app.domain.shipping import AddressDetails

router = APIRouter(prefix="/orders", tags=["orders"])


class ShippingAddressInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    recipient_name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    address_line1: str = Field(min_length=1, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=1, max_length=100)
    postal_code: str = Field(min_length=1, max_length=20)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    delivery_instructions: str | None = Field(default=None, max_length=1000)

    @field_validator("country_code", mode="before")
    @classmethod
    def normalize_country(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("phone", "address_line2", "delivery_instructions")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        return value or None


class ItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: int = Field(gt=0, le=2147483647, strict=True)
    quantity: int = Field(gt=0, le=2147483647, strict=True)


class CustomerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    phone: str = Field(min_length=1, max_length=50)
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class OrderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    shipping_address: ShippingAddressInput
    customer: CustomerInput
    items: list[ItemInput] = Field(min_length=1, max_length=1000)
    notes: str | None = Field(default=None, max_length=2000)
    credit_card_number: str = Field(pattern=r"^\d{13,19}$")
    payment_description: str = Field(min_length=1, max_length=255)

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


class DecisionCoordinatesOutput(BaseModel):
    latitude: float
    longitude: float


class WarehouseDecisionCandidateOutput(BaseModel):
    warehouse_id: int
    warehouse_name: str
    coordinates: DecisionCoordinatesOutput
    distance_km: float
    rank: int
    outcome: Literal["NOT_ATTEMPTED", "REJECTED", "SELECTED"]
    reason: str | None


class WarehouseDecisionOutput(BaseModel):
    version: int
    evaluated_at: datetime
    strategy: str
    shipping_coordinates: DecisionCoordinatesOutput
    selected_warehouse_id: int | None
    candidates: list[WarehouseDecisionCandidateOutput]


class OrderOutput(BaseModel):
    id: int
    status: Literal["CREATED", "BOOKED", "PAYING", "PAID", "CANCELLED"]
    shipping_address: dict
    latitude: float | None
    longitude: float | None
    warehouse_id: int | None
    warehouse_decision: WarehouseDecisionOutput | None
    total_amount: Decimal
    notes: str | None
    failure_reason: str | None
    payment_description: str | None
    payment_identifier: str | None
    customer: dict | None
    created_at: datetime
    updated_at: datetime
    items: list[ItemOutput]
    history: list[HistoryOutput]


Service = OrderServiceDependency


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
        customer=CustomerDetails(**data.customer.model_dump()),
        items=tuple(RequestedItem(i.product_id, i.quantity) for i in data.items),
        notes=data.notes,
        payment=PaymentDetails(
            credit_card_number=data.credit_card_number,
            description=data.payment_description,
        ),
    )
    try:
        order = await service.create(command, idempotency_key)
    except InvalidOrder as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except IdempotencyConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    response.headers["Location"] = f"/orders/{order.id}"
    if order.status in ("CREATED", "BOOKED", "PAYING"):
        response.status_code = 202
    return asdict(order)


@router.get("", response_model=list[OrderOutput])
async def list_orders(
    service: Service,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
):
    return [asdict(order) for order in await service.list(limit, offset)]


@router.get("/{order_id}", response_model=OrderOutput)
async def get_order(order_id: BoundedId, service: Service):
    try:
        return asdict(await service.get(order_id))
    except OrderNotFound as error:
        raise HTTPException(status_code=404, detail="Order not found.") from error
