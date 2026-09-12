import asyncio
from decimal import Decimal
from hashlib import sha256

from app.application.ports.payment import PaymentResponse, PaymentResult
from app.domain.order import PaymentDetails


class MockPaymentGateway:
    async def charge(
        self,
        payment: PaymentDetails | Decimal,
        amount: Decimal | None = None,
        *,
        idempotency_key: str,
    ) -> PaymentResponse:
        if amount is None:
            amount = payment if isinstance(payment, Decimal) else Decimal("0")
        await asyncio.sleep(2)
        # A stable pseudo-random result models provider idempotency, including after restart.
        rejected = int.from_bytes(sha256(idempotency_key.encode()).digest()) % 5 == 0
        if rejected:
            return PaymentResponse(PaymentResult.DECLINED)
        identifier = f"pay_{sha256(idempotency_key.encode()).hexdigest()[:32]}"
        return PaymentResponse(PaymentResult.SUCCEEDED, identifier)
