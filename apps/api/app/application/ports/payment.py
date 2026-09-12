from decimal import Decimal
from enum import Enum
from typing import Protocol


class PaymentResult(Enum):
    SUCCEEDED = "succeeded"
    DECLINED = "declined"


class PaymentUnavailable(Exception):
    """Outcome is unknown; retain the reservation until reconciliation."""


class PaymentGateway(Protocol):
    async def charge(self, amount: Decimal, *, idempotency_key: str) -> PaymentResult: ...
