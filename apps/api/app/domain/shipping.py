from dataclasses import dataclass


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
