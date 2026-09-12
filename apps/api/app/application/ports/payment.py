from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Protocol

from app.domain.order import PaymentDetails


class PaymentResult(Enum):
    SUCCEEDED = "succeeded"
    DECLINED = "declined"


@dataclass(frozen=True)
class PaymentResponse:
    result: PaymentResult
    identifier: str | None = None


class PaymentUnavailable(Exception):
    """Outcome is unknown; retain the reservation until reconciliation."""


class PaymentGateway(Protocol):
    async def charge(
        self, payment: PaymentDetails, amount: Decimal, *, idempotency_key: str
    ) -> PaymentResponse: ...
