from typing import Protocol

from app.domain.shipping_address import AddressDetails, Coordinates, ShippingAddress


class ShippingAddressRepository(Protocol):
    async def list(self) -> list[ShippingAddress]: ...

    async def get(self, address_id: int) -> ShippingAddress: ...

    async def create(
        self, details: AddressDetails, coordinates: Coordinates | None
    ) -> ShippingAddress: ...

    async def update(
        self, address_id: int, details: AddressDetails, coordinates: Coordinates | None
    ) -> ShippingAddress: ...

    async def delete(self, address_id: int) -> None: ...
