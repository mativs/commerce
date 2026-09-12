import asyncio

from app.application.ports.geocoder import Geocoder, GeocodingUnavailable
from app.application.ports.orders import OrderRepository
from app.application.ports.payment import PaymentGateway, PaymentResult, PaymentUnavailable
from app.domain.order import CreateOrder, OrderView, distance_km


class OrderService:
    def __init__(self, repository: OrderRepository, geocoder: Geocoder, payment: PaymentGateway):
        self.repository = repository
        self.geocoder = geocoder
        self.payment = payment

    async def create(self, command: CreateOrder, key: str) -> OrderView:
        order, created = await self.repository.create(command, key)
        if not created:
            # Replays observe durable state; they never start another payment/booking attempt.
            return order
        try:
            async with asyncio.timeout(10):
                coordinates = await self.geocoder.geocode(command.shipping_address)
        except (GeocodingUnavailable, TimeoutError):
            await self.repository.cancel(order.id, "GEOCODING_FAILED")
            return await self.repository.get(order.id)
        await self.repository.locate(order.id, coordinates)
        candidates = await self.repository.candidates(order.id)
        candidates.sort(
            key=lambda candidate: (distance_km(coordinates, candidate.coordinates), candidate.id)
        )
        for candidate in candidates:
            if await self.repository.reserve(order.id, candidate.id):
                break
        else:
            await self.repository.cancel(order.id, "OUT_OF_STOCK")
            return await self.repository.get(order.id)
        try:
            async with asyncio.timeout(10):
                result = await self.payment.charge(
                    order.total_amount, idempotency_key=f"order:{key}"
                )
        except (PaymentUnavailable, TimeoutError):
            # Do not release inventory for a payment that may have succeeded.
            return await self.repository.get(order.id)
        if result == PaymentResult.SUCCEEDED:
            await self.repository.pay(order.id)
        else:
            await self.repository.cancel(order.id, "PAYMENT_FAILED")
        return await self.repository.get(order.id)
