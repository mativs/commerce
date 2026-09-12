from dataclasses import asdict, fields
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.persistence.models import ShippingAddress as ShippingAddressRow
from app.domain.shipping_address import (
    AddressDetails,
    Coordinates,
    ShippingAddress,
    ShippingAddressNotFound,
)


def to_domain(row: ShippingAddressRow) -> ShippingAddress:
    return ShippingAddress(
        id=row.id,
        details=AddressDetails(
            **{field.name: getattr(row, field.name) for field in fields(AddressDetails)}
        ),
        coordinates=(
            Coordinates(latitude=row.latitude, longitude=row.longitude)
            if row.latitude is not None and row.longitude is not None
            else None
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
        deleted_at=row.deleted_at,
    )


class SqlAlchemyShippingAddressRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _find(self, address_id: int) -> ShippingAddressRow:
        row = await self.session.get(ShippingAddressRow, address_id)
        if row is None or row.deleted_at is not None:
            raise ShippingAddressNotFound
        return row

    async def list(self, limit: int = 50, offset: int = 0) -> list[ShippingAddress]:
        async with self.session.begin():
            rows = await self.session.scalars(
                select(ShippingAddressRow)
                .where(ShippingAddressRow.deleted_at.is_(None))
                .order_by(ShippingAddressRow.id)
                .limit(limit)
                .offset(offset)
            )
            return [to_domain(row) for row in rows]

    async def get(self, address_id: int) -> ShippingAddress:
        async with self.session.begin():
            return to_domain(await self._find(address_id))

    async def create(
        self, details: AddressDetails, coordinates: Coordinates | None
    ) -> ShippingAddress:
        async with self.session.begin():
            row = ShippingAddressRow(
                **asdict(details),
                **(asdict(coordinates) if coordinates else {"latitude": None, "longitude": None}),
            )
            self.session.add(row)
            await self.session.flush()
            result = to_domain(row)
        return result

    async def update(
        self, address_id: int, details: AddressDetails, coordinates: Coordinates | None
    ) -> ShippingAddress:
        async with self.session.begin():
            row = await self._find(address_id)
            for name, value in (
                asdict(details)
                | (asdict(coordinates) if coordinates else {"latitude": None, "longitude": None})
            ).items():
                setattr(row, name, value)
            await self.session.flush()
            await self.session.refresh(row)
            result = to_domain(row)
        return result

    async def delete(self, address_id: int) -> None:
        async with self.session.begin():
            row = await self._find(address_id)
            row.deleted_at = datetime.now(UTC)
