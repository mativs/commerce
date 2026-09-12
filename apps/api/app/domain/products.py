from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


class ProductNotFound(Exception):
    pass


@dataclass(frozen=True)
class StockView:
    warehouse_id: int
    warehouse_name: str
    on_hand: int
    reserved: int
    available: int


@dataclass(frozen=True)
class ProductView:
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
    stock: list[StockView]
