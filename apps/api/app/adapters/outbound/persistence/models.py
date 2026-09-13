from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    FetchedValue,
    Float,
    ForeignKey,
    Index,
    MetaData,
    Numeric,
    String,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class CreatedUpdatedMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TimestampMixin(CreatedUpdatedMixin):
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Warehouse(TimestampMixin, Base):
    __tablename__ = "warehouses"
    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    record_id: Mapped[int] = mapped_column(nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    old_values: Mapped[dict | None] = mapped_column(JSONB)
    new_values: Mapped[dict | None] = mapped_column(JSONB)


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price >= 0 AND price < 'Infinity'::numeric", name="price_range"),
        CheckConstraint("sku = upper(btrim(sku)) AND length(sku) > 0", name="sku_normalized"),
        CheckConstraint("ean IS NULL OR ean ~ '^([0-9]{8}|[0-9]{13})$'", name="ean_format"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    ean: Mapped[str | None] = mapped_column(String(13), unique=True)
    description: Mapped[str | None] = mapped_column(String(2000))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (CheckConstraint("email = lower(btrim(email))", name="email_normalized"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)


class Stock(CreatedUpdatedMixin, Base):
    """Physical and allocated whole units for one warehouse/product pair."""

    __tablename__ = "stock"
    __table_args__ = (
        UniqueConstraint("warehouse_id", "product_id", name="uq_stock_warehouse_product"),
        CheckConstraint("on_hand >= 0", name="on_hand_nonnegative"),
        CheckConstraint("reserved >= 0", name="reserved_nonnegative"),
        CheckConstraint("reserved <= on_hand", name="reserved_within_on_hand"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    on_hand: Mapped[int] = mapped_column(nullable=False, server_default="0")
    reserved: Mapped[int] = mapped_column(nullable=False, server_default="0")


class Order(Base):
    __tablename__ = "orders"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude_range"),
        CheckConstraint("(latitude IS NULL) = (longitude IS NULL)", name="coordinates_pair"),
        CheckConstraint(
            "status IN ('CREATED', 'BOOKED', 'PAYING', 'PAID', 'CANCELLED')", name="status_valid"
        ),
        CheckConstraint(
            "total_amount >= 0 AND total_amount < 'Infinity'::numeric", name="total_valid"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="CREATED")
    warehouse_decision: Mapped[dict | None] = mapped_column(JSONB)
    shipping_address: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    order_idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    payment_idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    request_hash: Mapped[str | None] = mapped_column(String(64))
    failure_reason: Mapped[str | None] = mapped_column(String(40))
    payment_description: Mapped[str | None] = mapped_column(String(255))
    credit_card_number: Mapped[str | None] = mapped_column(String(19))
    payment_identifier: Mapped[str | None] = mapped_column(String(128), unique=True)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), index=True
    )
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), index=True
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(22, 2), nullable=False, server_default="0"
    )
    notes: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
        server_onupdate=FetchedValue(),
    )


class OrderStatusHistory(Base):
    """Append-only status changes; use created_at and id for chronological ordering."""

    __tablename__ = "order_status_history"
    __table_args__ = (
        CheckConstraint(
            "status IN ('CREATED', 'BOOKED', 'PAYING', 'PAID', 'CANCELLED')", name="status_valid"
        ),
        Index("ix_order_status_history_chronology", "order_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )


class OrderItem(Base):
    """One product per order with a price captured when the item is inserted."""

    __tablename__ = "order_items"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        UniqueConstraint("order_id", "product_id", name="uq_order_items_order_product"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0 AND unit_price < 'Infinity'::numeric", name="price_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default=FetchedValue()
    )


class OrderValidationRun(Base):
    __tablename__ = "order_validation_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING','COMPLETED','PARTIAL','FAILED','INTERRUPTED')",
            name="status_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    parameters: Mapped[dict] = mapped_column(JSONB)
    rules_version: Mapped[int] = mapped_column(server_default="1")
    status: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrderValidationCheckResult(Base):
    __tablename__ = "order_validation_check_results"
    __table_args__ = (
        UniqueConstraint("run_id", "check_code"),
        CheckConstraint(
            "status IN ('PENDING','RUNNING','COMPLETED','FAILED','SKIPPED')", name="status_valid"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("order_validation_runs.id"))
    check_code: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finding_count: Mapped[int] = mapped_column(server_default="0")
    error: Mapped[str | None] = mapped_column(String(255))


class OrderValidationFinding(Base):
    __tablename__ = "order_validation_findings"
    __table_args__ = (Index("ix_validation_findings_check", "check_result_id", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    check_result_id: Mapped[int] = mapped_column(ForeignKey("order_validation_check_results.id"))
    order_id: Mapped[int | None]
    warehouse_id: Mapped[int | None]
    product_id: Mapped[int | None]
    severity: Mapped[str] = mapped_column(String(20))
    evidence: Mapped[dict] = mapped_column(JSONB)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
