import asyncio
import logging
from uuid import uuid4

from app.application.ports.geocoder import Geocoder, GeocodingUnavailable
from app.application.ports.orders import OrderRepository
from app.application.ports.payment import (
    PaymentDeclined,
    PaymentGateway,
    PaymentResponseInvalid,
    PaymentSucceeded,
    PaymentUnavailable,
)
from app.domain.order import CreateOrder, OrderView, distance_km

logger = logging.getLogger(__name__)


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

        # STEP 1: create the order in status CREATED
        order, created = await self.repository.create(
            command, order_idempotency_key, payment_idempotency_key
        )
        if not created:
            logger.info("order.replayed", extra={"order_id": order.id})
            # Replays observe durable state; they never start another payment/booking attempt.
            return order

        logger.info("order.created", extra={"order_id": order.id})

        # STEP 2: Get coordinates
        try:
            async with asyncio.timeout(10):
                coordinates = await self.geocoder.geocode(command.shipping_address)
        except (GeocodingUnavailable, TimeoutError):
            await self.repository.cancel(order.id, "GEOCODING_FAILED")
            logger.warning(
                "order.cancelled", extra={"order_id": order.id, "outcome": "GEOCODING_FAILED"}
            )
            return await self.repository.get(order.id)
        await self.repository.locate(order.id, coordinates)

        # STEP 3: For each warehouse with stock we try to reserve
        candidates = await self.repository.candidates(order.id)
        ranked = sorted(
            [
                (candidate, distance_km(coordinates, candidate.coordinates))
                for candidate in candidates
            ],
            key=lambda entry: (entry[1], entry[0].id),
        )
        await self.repository.record_warehouse_decision(order.id, coordinates, ranked)
        for candidate, _ in ranked:
            if await self.repository.reserve(order.id, candidate.id):
                break
        else:
            await self.repository.cancel(order.id, "OUT_OF_STOCK")
            logger.info("order.cancelled", extra={"order_id": order.id, "outcome": "OUT_OF_STOCK"})
            return await self.repository.get(order.id)

        # STEP 4: persist payment initiation before calling the gateway.
        await self.repository.start_payment(order.id)
        try:
            async with asyncio.timeout(10):
                result = await self.payment.charge(
                    command.payment,
                    order.total_amount,
                    idempotency_key=payment_idempotency_key,
                )
        except PaymentResponseInvalid:
            logger.warning(
                "order.payment_pending",
                extra={"order_id": order.id, "outcome": "PAYMENT_RESPONSE_INVALID"},
            )
            # Invalid provider data does not establish whether payment succeeded.
            return await self.repository.get(order.id)
        except (PaymentUnavailable, TimeoutError):
            logger.warning(
                "order.payment_pending",
                extra={"order_id": order.id, "outcome": "PAYMENT_UNAVAILABLE"},
            )
            # Do not release inventory for a payment that may have succeeded.
            return await self.repository.get(order.id)
        if isinstance(result, PaymentSucceeded):
            await self.repository.pay(order.id, result.reference)
            logger.info("order.paid", extra={"order_id": order.id})
        elif isinstance(result, PaymentDeclined):
            await self.repository.cancel(order.id, "PAYMENT_FAILED")
            logger.warning(
                "order.cancelled", extra={"order_id": order.id, "outcome": "PAYMENT_FAILED"}
            )
        else:
            logger.warning(
                "order.payment_pending",
                extra={"order_id": order.id, "outcome": "PAYMENT_RESPONSE_INVALID"},
            )
        return await self.repository.get(order.id)
