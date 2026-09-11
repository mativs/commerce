from dataclasses import asdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.adapters.inbound.http.dependencies import DatabaseSession
from app.adapters.inbound.http.warehouses import AuditLogOutput
from app.adapters.outbound.persistence.models import AuditLog
from app.adapters.outbound.persistence.models import ShippingAddress as ShippingAddressRow
from app.application.services.shipping_addresses import ShippingAddressService
from app.domain.shipping_address import AddressDetails, ShippingAddress

router = APIRouter(prefix="/shipping-addresses", tags=["shipping addresses"])


def get_shipping_address_service() -> ShippingAddressService:
    # Installed by the composition root; adapters never choose a geocoding provider.
    raise RuntimeError("Shipping address service is not configured.")


AddressService = Annotated[ShippingAddressService, Depends(get_shipping_address_service)]


class ShippingAddressInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    recipient_name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    address_line1: str = Field(min_length=1, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=1, max_length=100)
    postal_code: str = Field(min_length=1, max_length=20)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    delivery_instructions: str | None = Field(default=None, max_length=1000)

    @field_validator("country_code", mode="before")
    @classmethod
    def normalize_country(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("phone", "address_line2", "delivery_instructions")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        return value or None


class ShippingAddressOutput(ShippingAddressInput):
    id: int
    latitude: float
    longitude: float
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    @classmethod
    def from_domain(cls, address: ShippingAddress) -> "ShippingAddressOutput":
        return cls(
            **asdict(address.details),
            **asdict(address.coordinates),
            id=address.id,
            created_at=address.created_at,
            updated_at=address.updated_at,
            deleted_at=address.deleted_at,
        )


@router.get("", response_model=list[ShippingAddressOutput])
async def list_addresses(service: AddressService):
    return [ShippingAddressOutput.from_domain(address) for address in await service.list()]


@router.post("", response_model=ShippingAddressOutput, status_code=status.HTTP_201_CREATED)
async def create_address(data: ShippingAddressInput, service: AddressService, response: Response):
    address = await service.create(AddressDetails(**data.model_dump()))
    response.headers["Location"] = f"/shipping-addresses/{address.id}"
    return ShippingAddressOutput.from_domain(address)


@router.get("/{address_id}", response_model=ShippingAddressOutput)
async def get_address(address_id: int, service: AddressService):
    return ShippingAddressOutput.from_domain(await service.get(address_id))


@router.put("/{address_id}", response_model=ShippingAddressOutput)
async def update_address(address_id: int, data: ShippingAddressInput, service: AddressService):
    return ShippingAddressOutput.from_domain(
        await service.update(address_id, AddressDetails(**data.model_dump()))
    )


@router.delete("/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_address(address_id: int, service: AddressService):
    await service.delete(address_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{address_id}/logs", response_model=list[AuditLogOutput])
async def address_logs(address_id: int, session: DatabaseSession):
    if await session.get(ShippingAddressRow, address_id) is None:
        raise HTTPException(status_code=404, detail="Shipping address not found.")
    return (
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.table_name == "shipping_addresses", AuditLog.record_id == address_id)
            .order_by(AuditLog.id)
        )
    ).all()
