from secrets import randbelow

from app.adapters.outbound.geocoding.sample_locations import random_mar_del_plata_coordinates
from app.application.ports.geocoder import GeocodingUnavailable
from app.domain.shipping_address import AddressDetails, Coordinates


class MockGeocoder:
    def __init__(self, *, simulate_failures: bool = False):
        self.simulate_failures = simulate_failures

    async def geocode(self, address: AddressDetails) -> Coordinates:
        # The mock intentionally ignores the address. A real adapter can await HTTP here.
        if self.simulate_failures and randbelow(5) == 0:
            raise GeocodingUnavailable("Mock geocoding failed.")
        return random_mar_del_plata_coordinates()
