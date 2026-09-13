"""Definitions and SQL resources for order integrity checks."""

from dataclasses import dataclass, field
from importlib.resources import files
from typing import Literal

from sqlalchemy import TextClause, text

Severity = Literal["ERROR", "WARNING"]


@dataclass(frozen=True)
class ValidationCheck:
    """A packaged SQL check and the values needed to execute it."""

    query: TextClause
    severity: Severity
    parameters: dict[str, str] = field(default_factory=dict)
    threshold_key: str | None = None


def load_query(filename: str) -> TextClause:
    sql = (
        files(__package__).joinpath("sql", "order_validation", filename).read_text(encoding="utf-8")
    )
    return text(sql)


STALE_ORDER = load_query("stale_order.sql")


CHECKS: dict[str, ValidationCheck] = {
    "ORDER_TOTAL_MISMATCH": ValidationCheck(load_query("order_total_mismatch.sql"), "ERROR"),
    "ORDER_STUCK_CREATED": ValidationCheck(
        STALE_ORDER,
        "WARNING",
        parameters={"status": "CREATED"},
        threshold_key="created_age_seconds",
    ),
    "PAYMENT_NOT_STARTED": ValidationCheck(
        STALE_ORDER,
        "WARNING",
        parameters={"status": "BOOKED"},
        threshold_key="booked_age_seconds",
    ),
    "PAYMENT_PENDING_TOO_LONG": ValidationCheck(
        STALE_ORDER,
        "WARNING",
        parameters={"status": "PAYING"},
        threshold_key="payment_age_seconds",
    ),
    "PAID_WITHOUT_REFERENCE": ValidationCheck(load_query("paid_without_reference.sql"), "ERROR"),
    "INVENTORY_RESERVATION_MISMATCH": ValidationCheck(
        load_query("inventory_reservation_mismatch.sql"), "ERROR"
    ),
    "INVALID_ORDER_STRUCTURE": ValidationCheck(load_query("invalid_order_structure.sql"), "ERROR"),
    "INCONSISTENT_STATUS_HISTORY": ValidationCheck(
        load_query("inconsistent_status_history.sql"), "ERROR"
    ),
}
