"""Always-on exercise scenarios selected by plain keywords in order notes.

Only this composition layer knows about markers; the real order workflow and
repository handle all state transitions, inventory updates, and idempotency.
"""

import re
from decimal import Decimal

from app.application.ports.geocoder import Geocoder
from app.application.ports.payment import (
    PaymentGateway,
    PaymentResponse,
    PaymentResult,
    PaymentUnavailable,
)
from app.application.services.orders import OrderService
from app.domain.order import CreateOrder, OrderView, PaymentDetails
from app.domain.shipping import AddressDetails, Coordinates

MARKER = re.compile(
    r"(?<![\w-])(geocoding-timeout|payment-timeout|payment-declined|payment-failed)(?![\w-])",
    re.IGNORECASE,
)


class SimulatedGeocoder:
    def __init__(self, delegate: Geocoder, marker: str | None):
        self.delegate = delegate
        self.marker = marker

    async def geocode(self, address: AddressDetails) -> Coordinates:
        if self.marker == "geocoding-timeout":
            raise TimeoutError("Simulated geocoding timeout")
        return await self.delegate.geocode(address)


class SimulatedPaymentGateway:
    def __init__(self, delegate: PaymentGateway, marker: str | None):
        self.delegate = delegate
        self.marker = marker

    async def charge(
        self, payment: PaymentDetails, amount: Decimal, *, idempotency_key: str
    ) -> PaymentResponse:
        if self.marker == "payment-timeout":
            raise TimeoutError("Simulated payment timeout")
        if self.marker == "payment-failed":
            raise PaymentUnavailable("Simulated payment provider failure")
        if self.marker == "payment-declined":
            return PaymentResponse(PaymentResult.DECLINED)
        return await self.delegate.charge(payment, amount, idempotency_key=idempotency_key)


class SimulatedOrderService(OrderService):
    """Select the first marker and compose isolated adapters for this invocation."""

    async def create(self, command: CreateOrder, order_idempotency_key: str) -> OrderView:
        match = MARKER.search(command.notes or "")
        marker = match.group(0).lower() if match else None
        service = OrderService(
            self.repository,
            SimulatedGeocoder(self.geocoder, marker),
            SimulatedPaymentGateway(self.payment, marker),
        )
        return await service.create(command, order_idempotency_key)
