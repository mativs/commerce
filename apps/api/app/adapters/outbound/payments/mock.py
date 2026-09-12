import asyncio
from decimal import Decimal
from hashlib import sha256

from app.application.ports.payment import PaymentResult


class MockPaymentGateway:
    async def charge(self, amount: Decimal, *, idempotency_key: str) -> PaymentResult:
        await asyncio.sleep(2)
        # A stable pseudo-random result models provider idempotency, including after restart.
        rejected = int.from_bytes(sha256(idempotency_key.encode()).digest()) % 5 == 0
        return PaymentResult.DECLINED if rejected else PaymentResult.SUCCEEDED
