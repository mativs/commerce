import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.adapters.outbound.payments.mock import MockPaymentGateway
from app.application.ports.payment import PaymentResponseInvalid, PaymentSucceeded
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
                outcomes.append(result)
            assert all(isinstance(outcome, PaymentSucceeded) for outcome in outcomes)
            assert sleep.await_count == 40
            sleep.assert_awaited_with(2)

    asyncio.run(check())


@pytest.mark.parametrize("reference", [None, "", "   ", "a" * 129])
def test_success_rejects_invalid_provider_reference(reference):
    with pytest.raises(PaymentResponseInvalid, match="1 to 128 characters"):
        PaymentSucceeded(reference)


def test_success_accepts_maximum_length_provider_reference():
    assert PaymentSucceeded("a" * 128).reference == "a" * 128
