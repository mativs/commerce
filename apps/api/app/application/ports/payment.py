from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.domain.order import PaymentDetails


class PaymentUnavailable(Exception):
    """Outcome is unknown; retain the reservation until reconciliation."""


class PaymentResponseInvalid(PaymentUnavailable):
    """The provider returned data that cannot be treated as a payment outcome."""


@dataclass(frozen=True)
class PaymentSucceeded:
    reference: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.reference, str)
            or not self.reference.strip()
            or len(self.reference) > 128
        ):
            raise PaymentResponseInvalid(
                "A successful payment requires a provider reference of 1 to 128 characters."
            )


@dataclass(frozen=True)
class PaymentDeclined:
    pass


PaymentResponse = PaymentSucceeded | PaymentDeclined


class PaymentGateway(Protocol):
    async def charge(
        self, payment: PaymentDetails, amount: Decimal, *, idempotency_key: str
    ) -> PaymentResponse: ...
