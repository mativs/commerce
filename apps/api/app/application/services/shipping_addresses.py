from app.application.ports.geocoder import Geocoder
from app.application.ports.shipping_addresses import ShippingAddressRepository
from app.domain.shipping_address import AddressDetails, ShippingAddress


class ShippingAddressService:
    def __init__(self, repository: ShippingAddressRepository, geocoder: Geocoder):
        self.repository = repository
        self.geocoder = geocoder

    async def list(self, limit: int = 50, offset: int = 0) -> list[ShippingAddress]:
        return await self.repository.list(limit, offset)

    async def get(self, address_id: int) -> ShippingAddress:
        return await self.repository.get(address_id)

    async def create(self, details: AddressDetails) -> ShippingAddress:
        coordinates = await self.geocoder.geocode(details)
        return await self.repository.create(details, coordinates)

    async def update(self, address_id: int, details: AddressDetails) -> ShippingAddress:
        existing = await self.repository.get(address_id)
        coordinates = existing.coordinates
        if details.location_key != existing.details.location_key:
            coordinates = await self.geocoder.geocode(details)
        return await self.repository.update(address_id, details, coordinates)

    async def delete(self, address_id: int) -> None:
        await self.repository.delete(address_id)
