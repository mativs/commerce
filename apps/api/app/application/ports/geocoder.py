from typing import Protocol

from app.domain.shipping import AddressDetails, Coordinates


class GeocodingUnavailable(Exception):
    """An outbound geocoder could not resolve the address."""


class Geocoder(Protocol):
    async def geocode(self, address: AddressDetails) -> Coordinates:
        """Resolve an address or raise GeocodingUnavailable."""
        ...
