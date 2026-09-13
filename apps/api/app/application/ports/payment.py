from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.domain.order import PaymentDetails


@dataclass(frozen=True)
class PaymentSucceeded:
    reference: str

    def __post_init__(self) -> None:
        if not isinstance(self.reference, str) or not self.reference.strip():
            raise ValueError("A successful payment requires a nonempty provider reference.")


@dataclass(frozen=True)
class PaymentDeclined:
    pass


PaymentResponse = PaymentSucceeded | PaymentDeclined


class PaymentUnavailable(Exception):
    """Outcome is unknown; retain the reservation until reconciliation."""


class PaymentGateway(Protocol):
    async def charge(
        self, payment: PaymentDetails, amount: Decimal, *, idempotency_key: str
    ) -> PaymentResponse: ...
