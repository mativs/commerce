import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from app.adapters.outbound.payments.mock import MockPaymentGateway
from app.application.ports.payment import PaymentResult
from app.domain.order import PaymentDetails


def test_mock_payment_always_succeeds_with_delay_and_stable_reference():
    async def check():
        with patch(
            "app.adapters.outbound.payments.mock.asyncio.sleep", new_callable=AsyncMock
        ) as sleep:
            gateway = MockPaymentGateway()
            outcomes = []
            for number in range(20):
                key = f"order:{number}"
                payment = PaymentDetails(credit_card_number="4111111111111111", description="test")
                result = await gateway.charge(payment, Decimal("12.34"), idempotency_key=key)
                assert result == await MockPaymentGateway().charge(
                    payment, Decimal("12.34"), idempotency_key=key
                )
                outcomes.append(result.result)
            assert set(outcomes) == {PaymentResult.SUCCEEDED}
            assert sleep.await_count == 40
            sleep.assert_awaited_with(2)

    asyncio.run(check())
