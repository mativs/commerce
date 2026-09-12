import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.adapters.outbound.geocoding.sample_locations import MAR_DEL_PLATA_LOCATIONS
from app.application.ports.geocoder import GeocodingUnavailable
from app.domain.shipping_address import Coordinates

ADDRESS = {
    "recipient_name": "  Ana Pérez  ",
    "phone": "+54 223 555 0100",
    "address_line1": "San Martín 2500",
    "address_line2": "Floor 2, apartment B",
    "city": "Mar del Plata",
    "state": "Buenos Aires",
    "postal_code": "B7600",
    "country_code": "ar",
    "delivery_instructions": "Ring the bell",
}


def test_address_crud_and_audit(database_client):
    client, _ = database_client
    assert client.get("/shipping-addresses").json() == []
    response = client.post("/shipping-addresses", json=ADDRESS)
    assert response.status_code == 201
    address = response.json()
    url = response.headers["location"]
    assert address["recipient_name"] == "Ana Pérez"
    assert address["country_code"] == "AR"
    assert (address["latitude"], address["longitude"]) in MAR_DEL_PLATA_LOCATIONS
    assert address["created_at"] and address["updated_at"]
    assert address["deleted_at"] is None
    assert client.get(url).json() == address
    assert client.get("/shipping-addresses").json() == [address]

    updated = client.put(url, json={**ADDRESS, "phone": None, "recipient_name": "Juan"})
    assert updated.status_code == 200
    assert updated.json()["latitude"] == address["latitude"]
    assert updated.json()["longitude"] == address["longitude"]
    assert updated.json()["updated_at"] != address["updated_at"]
    assert updated.json()["created_at"] == address["created_at"]
    assert client.get(url).json() == updated.json()
    logs = client.get(f"{url}/logs").json()
    assert [log["action"] for log in logs] == ["create", "update"]
    assert logs[1]["old_values"]["recipient_name"] == "Ana Pérez"
    assert logs[1]["new_values"]["recipient_name"] == "Juan"
    assert logs[1]["new_values"]["phone"] is None

    deleted = client.delete(url)
    assert deleted.status_code == 204 and deleted.content == b""
    assert client.get("/shipping-addresses").json() == []
    assert client.get(url).status_code == 404
    assert client.put(url, json=ADDRESS).status_code == 404
    assert client.delete(url).status_code == 404
    logs = client.get(f"{url}/logs").json()
    assert [log["action"] for log in logs] == ["create", "update", "delete"]
    assert logs[-1]["new_values"]["deleted_at"] is not None
    assert client.get("/shipping-addresses/2147483647/logs").status_code == 404


def test_geocoding_runs_only_for_location_changes(database_client):
    client, _ = database_client
    geocoder = AsyncMock()
    geocoder.geocode.return_value = Coordinates(latitude=-38, longitude=-57.57)
    client.app.state.geocoder = geocoder
    response = client.post("/shipping-addresses", json=ADDRESS)
    url = response.headers["location"]
    geocoder.geocode.assert_awaited_once()
    assert geocoder.geocode.call_args.args[0].city == "Mar del Plata"
    assert response.json()["latitude"] == -38
    assert client.put(url, json={**ADDRESS, "phone": "123"}).status_code == 200
    assert geocoder.geocode.await_count == 1
    geocoder.geocode.return_value = Coordinates(latitude=-38.005, longitude=-57.58)
    moved = client.put(url, json={**ADDRESS, "address_line1": "San Martín 2600"})
    assert moved.status_code == 200
    assert moved.json()["latitude"] == -38.005
    assert moved.json()["longitude"] == -57.58
    assert geocoder.geocode.await_count == 2
    logs = client.get(f"{url}/logs").json()
    assert logs[-1]["old_values"]["latitude"] == -38
    assert logs[-1]["new_values"]["latitude"] == -38.005


def test_geocoding_failure_does_not_save_or_audit(database_client):
    client, sessions = database_client
    geocoder = AsyncMock()
    geocoder.geocode.side_effect = GeocodingUnavailable("Provider timeout")
    client.app.state.geocoder = geocoder
    assert client.post("/shipping-addresses", json=ADDRESS).status_code == 503
    assert client.get("/shipping-addresses").json() == []

    async def count_logs():
        async with sessions() as session:
            return await session.scalar(text("SELECT count(*) FROM audit_logs"))

    assert asyncio.run(count_logs()) == 0
    geocoder.geocode.side_effect = None
    geocoder.geocode.return_value = Coordinates(latitude=-38, longitude=-57.57)
    created = client.post("/shipping-addresses", json=ADDRESS)
    url = created.headers["location"]
    geocoder.geocode.side_effect = GeocodingUnavailable()
    assert client.put(url, json={**ADDRESS, "city": "Another city"}).status_code == 503
    assert client.get(url).json() == created.json()
    assert len(client.get(f"{url}/logs").json()) == 1


@pytest.mark.parametrize(
    "invalid",
    [
        {"recipient_name": " "},
        {"address_line1": " "},
        {"city": ""},
        {"state": None},
        {"postal_code": "x" * 21},
        {"country_code": "Argentina"},
        {"country_code": "12"},
        {"latitude": -38},
        {"longitude": -57.57},
        {"phone": "x" * 51},
        {"delivery_instructions": "x" * 1001},
    ],
)
def test_address_validation(database_client, invalid):
    client, _ = database_client
    geocoder = AsyncMock()
    client.app.state.geocoder = geocoder
    assert client.post("/shipping-addresses", json={**ADDRESS, **invalid}).status_code == 422
    assert client.put("/shipping-addresses/1", json={**ADDRESS, **invalid}).status_code == 422
    geocoder.geocode.assert_not_awaited()


def test_optional_fields(database_client):
    client, _ = database_client
    required = {
        key: value
        for key, value in ADDRESS.items()
        if key not in {"phone", "address_line2", "delivery_instructions"}
    }
    response = client.post("/shipping-addresses", json=required)
    assert response.status_code == 201
    assert response.json()["phone"] is None
    url = response.headers["location"]
    response = client.put(url, json={**required, "phone": " ", "address_line2": " "})
    assert response.status_code == 200
    assert response.json()["phone"] is None
    assert response.json()["address_line2"] is None


def test_database_constraints_and_transactional_audit(database_client):
    client, sessions = database_client
    created = client.post("/shipping-addresses", json=ADDRESS)
    address_id = created.json()["id"]

    async def check():
        async with sessions() as session:
            types = (
                (
                    await session.execute(
                        text(
                            "SELECT data_type FROM information_schema.columns "
                            "WHERE table_schema = current_schema() "
                            "AND table_name = 'shipping_addresses' "
                            "AND column_name IN ('latitude', 'longitude')"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert types == ["double precision", "double precision"]
        for latitude, longitude in [(-91, 0), (91, 0), (0, -181), (0, 181)]:
            async with sessions() as session:
                with pytest.raises(IntegrityError):
                    await session.execute(
                        text(
                            "UPDATE shipping_addresses SET latitude = :latitude, "
                            "longitude = :longitude "
                            "WHERE id = :id"
                        ),
                        {"latitude": latitude, "longitude": longitude, "id": address_id},
                    )
                await session.rollback()
        async with sessions() as session:
            await session.execute(
                text("UPDATE shipping_addresses SET recipient_name = 'Rolled back' WHERE id = :id"),
                {"id": address_id},
            )
            await session.rollback()
        async with sessions() as session, session.begin():
            await session.execute(
                text("UPDATE shipping_addresses SET recipient_name = 'Direct SQL' WHERE id = :id"),
                {"id": address_id},
            )

    asyncio.run(check())
    logs = client.get(f"/shipping-addresses/{address_id}/logs").json()
    assert [log["action"] for log in logs] == ["create", "update"]
    assert logs[-1]["new_values"]["recipient_name"] == "Direct SQL"
