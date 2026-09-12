import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from app.adapters.outbound.payments.mock import MockPaymentGateway
from app.application.ports.payment import PaymentResult


def test_mock_payment_delay_idempotency_and_outcomes():
    async def check():
        with patch(
            "app.adapters.outbound.payments.mock.asyncio.sleep", new_callable=AsyncMock
        ) as sleep:
            gateway = MockPaymentGateway()
            outcomes = []
            for number in range(20):
                key = f"order:{number}"
                result = await gateway.charge(Decimal("12.34"), idempotency_key=key)
                assert result == await MockPaymentGateway().charge(
                    Decimal("12.34"), idempotency_key=key
                )
                outcomes.append(result.result)
            assert set(outcomes) == {PaymentResult.SUCCEEDED, PaymentResult.DECLINED}
            assert sleep.await_count == 40
            sleep.assert_awaited_with(2)

    asyncio.run(check())
