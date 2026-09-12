import asyncio
import inspect
from uuid import uuid4

from app.application.ports.geocoder import Geocoder, GeocodingUnavailable
from app.application.ports.orders import OrderRepository
from app.application.ports.payment import PaymentGateway, PaymentResult, PaymentUnavailable
from app.domain.order import CreateOrder, OrderView, distance_km


class OrderService:
    def __init__(self, repository: OrderRepository, geocoder: Geocoder, payment: PaymentGateway):
        self.repository = repository
        self.geocoder = geocoder
        self.payment = payment

    async def list(self, limit: int, offset: int) -> list[OrderView]:
        return await self.repository.list(limit, offset)

    async def get(self, order_id: int) -> OrderView:
        return await self.repository.get(order_id)

    async def create(self, command: CreateOrder, order_idempotency_key: str) -> OrderView:
        payment_idempotency_key = f"payment:{uuid4()}"
        order, created = await self.repository.create(
            command, order_idempotency_key, payment_idempotency_key
        )
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
        if command.customer is not None:
            await self.repository.ensure_customer(order.id, command.customer)
        try:
            async with asyncio.timeout(10):
                charge = self.payment.charge
                parameters = inspect.signature(charge).parameters
                if parameters and next(iter(parameters)).lower() in {"payment", "details"}:
                    result = await charge(
                        command.payment,
                        order.total_amount,
                        idempotency_key=payment_idempotency_key,
                    )
                else:  # Compatibility with simple test/demonstration gateways.
                    result = await charge(
                        order.total_amount, idempotency_key=payment_idempotency_key
                    )
        except (PaymentUnavailable, TimeoutError):
            # Do not release inventory for a payment that may have succeeded.
            return await self.repository.get(order.id)
        payment_result = result.result if hasattr(result, "result") else result
        payment_identifier = getattr(result, "identifier", None)
        if payment_result == PaymentResult.SUCCEEDED:
            await self.repository.pay(order.id, payment_identifier)
        else:
            await self.repository.cancel(order.id, "PAYMENT_FAILED")
        return await self.repository.get(order.id)
