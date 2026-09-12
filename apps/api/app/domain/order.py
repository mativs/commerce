from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from math import asin, cos, radians, sin, sqrt

from app.domain.shipping_address import AddressDetails, Coordinates


@dataclass(frozen=True)
class RequestedItem:
    product_id: int
    quantity: int


@dataclass(frozen=True)
class CreateOrder:
    shipping_address: AddressDetails
    items: tuple[RequestedItem, ...]
    notes: str | None = None


@dataclass(frozen=True)
class WarehouseCandidate:
    id: int
    coordinates: Coordinates


@dataclass(frozen=True)
class OrderItemView:
    product_id: int
    quantity: int
    unit_price: Decimal


@dataclass(frozen=True)
class StatusChange:
    status: str
    reason: str | None
    created_at: datetime


@dataclass(frozen=True)
class OrderView:
    id: int
    status: str
    shipping_address: dict
    latitude: float | None
    longitude: float | None
    warehouse_id: int | None
    total_amount: Decimal
    notes: str | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemView]
    history: list[StatusChange]


class InvalidOrder(Exception):
    pass


class IdempotencyConflict(Exception):
    pass


class OrderNotFound(Exception):
    pass


def distance_km(start: Coordinates, end: Coordinates) -> float:
    """Great-circle distance; clamp rounding error at antipodal points."""
    lat1, lat2 = radians(start.latitude), radians(end.latitude)
    dlat = lat2 - lat1
    dlon = radians(end.longitude - start.longitude)
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6371.0088 * 2 * asin(sqrt(min(1.0, max(0.0, a))))
