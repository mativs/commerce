from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, kw_only=True)
class Coordinates:
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not (-90 <= self.latitude <= 90 and -180 <= self.longitude <= 180):
            raise ValueError("Coordinates are outside geographic bounds.")


@dataclass(frozen=True, kw_only=True)
class AddressDetails:
    recipient_name: str
    address_line1: str
    city: str
    state: str
    postal_code: str
    country_code: str
    phone: str | None = None
    address_line2: str | None = None
    delivery_instructions: str | None = None

    @property
    def location_key(self) -> tuple[str | None, ...]:
        return (
            self.address_line1,
            self.address_line2,
            self.city,
            self.state,
            self.postal_code,
            self.country_code,
        )


@dataclass(frozen=True, kw_only=True)
class ShippingAddress:
    id: int
    details: AddressDetails
    coordinates: Coordinates
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class ShippingAddressNotFound(Exception):
    pass
