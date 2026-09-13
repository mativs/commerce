import asyncio
from decimal import Decimal
from hashlib import sha256

from app.application.ports.payment import PaymentResponse, PaymentSucceeded
from app.domain.order import PaymentDetails


class MockPaymentGateway:
    async def charge(
        self,
        payment: PaymentDetails,
        amount: Decimal,
        *,
        idempotency_key: str,
    ) -> PaymentResponse:
        await asyncio.sleep(2)
        # Keep the provider reference stable across retries and restarts.
        identifier = f"pay_{sha256(idempotency_key.encode()).hexdigest()[:32]}"
        return PaymentSucceeded(identifier)
