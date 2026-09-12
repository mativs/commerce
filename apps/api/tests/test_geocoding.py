import asyncio
from unittest.mock import patch

import pytest

from app.adapters.outbound.geocoding.mock import MockGeocoder
from app.adapters.outbound.geocoding.sample_locations import (
    MAR_DEL_PLATA_LOCATIONS,
    random_mar_del_plata_coordinates,
)
from app.domain.shipping import AddressDetails, Coordinates

DETAILS = AddressDetails(
    recipient_name="Ana",
    address_line1="San Martín 2500",
    city="Mar del Plata",
    state="Buenos Aires",
    postal_code="B7600",
    country_code="AR",
)


def test_mock_pool_and_selection():
    assert len(MAR_DEL_PLATA_LOCATIONS) == len(set(MAR_DEL_PLATA_LOCATIONS)) == 100
    assert all(
        -38.01 < lat < -37.98 and -57.60 < lon < -57.56 for lat, lon in MAR_DEL_PLATA_LOCATIONS
    )
    with patch("app.adapters.outbound.geocoding.sample_locations.choice") as choice:
        choice.side_effect = [MAR_DEL_PLATA_LOCATIONS[0], MAR_DEL_PLATA_LOCATIONS[-1]]
        first = random_mar_del_plata_coordinates()
        last = random_mar_del_plata_coordinates()
        assert first != last
        choice.assert_called_with(MAR_DEL_PLATA_LOCATIONS)
    coordinates = asyncio.run(MockGeocoder().geocode(DETAILS))
    assert (coordinates.latitude, coordinates.longitude) in MAR_DEL_PLATA_LOCATIONS


@pytest.mark.parametrize("latitude,longitude", [(float("nan"), 0), (0, float("inf")), (91, 0)])
def test_invalid_provider_coordinates_rejected(latitude, longitude):
    with pytest.raises(ValueError):
        Coordinates(latitude=latitude, longitude=longitude)
