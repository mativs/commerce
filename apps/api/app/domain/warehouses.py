from dataclasses import dataclass
from datetime import datetime


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
