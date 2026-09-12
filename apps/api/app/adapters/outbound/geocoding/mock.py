from app.adapters.outbound.geocoding.sample_locations import random_mar_del_plata_coordinates
from app.domain.shipping import AddressDetails, Coordinates


class MockGeocoder:
    async def geocode(self, address: AddressDetails) -> Coordinates:
        # The mock intentionally ignores the address. A real adapter can await HTTP here.
        return random_mar_del_plata_coordinates()
