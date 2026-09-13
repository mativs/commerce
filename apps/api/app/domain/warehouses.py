from dataclasses import dataclass
from datetime import datetime
from typing import Literal


class WarehouseNotFound(Exception):
    pass


@dataclass(frozen=True)
class WarehouseView:
    id: int
    name: str
    latitude: float
    longitude: float
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


StockFilter = Literal["all", "available", "on_hand"]


@dataclass(frozen=True)
class WarehouseProductView:
    product_id: int
    name: str
    sku: str
    on_hand: int
    booked: int
    available: int
