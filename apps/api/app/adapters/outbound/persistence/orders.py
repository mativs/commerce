import hashlib
import json
from dataclasses import asdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.persistence.models import (
    Customer,
    Order,
    OrderItem,
    OrderStatusHistory,
    Product,
    Stock,
    Warehouse,
)
from app.domain.order import (
    CreateOrder,
    CustomerDetails,
    IdempotencyConflict,
    InvalidOrder,
    OrderItemView,
    OrderNotFound,
    OrderView,
    StatusChange,
    WarehouseCandidate,
)
from app.domain.shipping import Coordinates


class SqlAlchemyOrderRepository:
    """Each write method owns a short transaction; no external IO runs inside it."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _order(self, order_id: int, *, lock: bool = False) -> Order:
        query = select(Order).where(Order.id == order_id).execution_options(populate_existing=True)
        if lock:
            query = query.with_for_update()
        row = await self.session.scalar(query)
        if row is None:
            raise OrderNotFound
        return row

    async def _items(self, order_id: int) -> list[OrderItem]:
        return list(
            await self.session.scalars(
                select(OrderItem)
                .where(OrderItem.order_id == order_id)
                .order_by(OrderItem.product_id)
            )
        )

    async def _view(self, row: Order) -> OrderView:
        items = await self._items(row.id)
        history = await self.session.scalars(
            select(OrderStatusHistory)
            .where(OrderStatusHistory.order_id == row.id)
            .order_by(OrderStatusHistory.created_at, OrderStatusHistory.id)
        )
        return OrderView(
            id=row.id,
            status=row.status,
            shipping_address=row.shipping_address,
            latitude=row.latitude,
            longitude=row.longitude,
            warehouse_id=row.warehouse_id,
            total_amount=row.total_amount,
            notes=row.notes,
            failure_reason=row.failure_reason,
            payment_description=row.payment_description,
            payment_identifier=row.payment_identifier,
            customer=(
                {
                    "id": customer.id,
                    "first_name": customer.first_name,
                    "last_name": customer.last_name,
                    "phone": customer.phone,
                    "email": customer.email,
                }
                if (customer := await self.session.get(Customer, row.customer_id)) is not None
                else None
            ),
            created_at=row.created_at,
            updated_at=row.updated_at,
            items=[OrderItemView(i.product_id, i.quantity, i.unit_price) for i in items],
            history=[StatusChange(h.status, h.reason, h.created_at) for h in history],
        )

    async def create(
        self, command: CreateOrder, order_idempotency_key: str, payment_idempotency_key: str
    ) -> tuple[OrderView, bool]:
        fingerprint = hashlib.sha256(
            json.dumps(asdict(command), sort_keys=True).encode()
        ).hexdigest()
        async with self.session.begin():
            # Unique index serializes concurrent submissions of the same key.
            order_id = await self.session.scalar(
                insert(Order)
                .values(
                    shipping_address=asdict(command.shipping_address),
                    notes=command.notes,
                    order_idempotency_key=order_idempotency_key,
                    payment_idempotency_key=payment_idempotency_key,
                    request_hash=fingerprint,
                    payment_description=command.payment.description,
                    credit_card_number=command.payment.credit_card_number,
                )
                .on_conflict_do_nothing(index_elements=[Order.order_idempotency_key])
                .returning(Order.id)
            )
            if order_id is None:
                row = await self.session.scalar(
                    select(Order)
                    .where(Order.order_idempotency_key == order_idempotency_key)
                    .with_for_update(read=True)
                )
                if row.request_hash != fingerprint:
                    raise IdempotencyConflict("This idempotency key belongs to a different order.")
                return await self._view(row), False
            product_ids = [item.product_id for item in command.items]
            # Shared locks preserve catalog price/eligibility until snapshots and total are saved.
            products = list(
                await self.session.scalars(
                    select(Product)
                    .where(Product.id.in_(product_ids))
                    .order_by(Product.id)
                    .with_for_update(read=True)
                )
            )
            if len(products) != len(product_ids) or any(
                p.deleted_at is not None or not p.is_active for p in products
            ):
                raise InvalidOrder("Every product must exist and be active.")
            items = [
                OrderItem(order_id=order_id, product_id=i.product_id, quantity=i.quantity)
                for i in command.items
            ]
            self.session.add_all(items)
            await self.session.flush()
            row = await self._order(order_id)
            row.total_amount = sum((i.unit_price * i.quantity for i in items), Decimal("0.00"))
            if row.total_amount >= Decimal("1e20"):
                raise InvalidOrder("Order total exceeds the supported amount.")
            await self.session.flush()
            return await self._view(row), True

    async def locate(self, order_id: int, coordinates: Coordinates) -> None:
        async with self.session.begin():
            row = await self._order(order_id, lock=True)
            if row.status == "CREATED" and row.latitude is None:
                row.latitude, row.longitude = coordinates.latitude, coordinates.longitude

    async def candidates(self, order_id: int) -> list[WarehouseCandidate]:
        async with self.session.begin():
            items = await self._items(order_id)
            quantities = {i.product_id: i.quantity for i in items}
            rows = (
                await self.session.execute(
                    select(Warehouse, Stock.product_id, Stock.on_hand, Stock.reserved)
                    .join(Stock, Stock.warehouse_id == Warehouse.id)
                    .where(
                        Warehouse.deleted_at.is_(None),
                        Stock.deleted_at.is_(None),
                        Stock.product_id.in_(quantities),
                    )
                )
            ).all()
            eligible: dict[int, set[int]] = {}
            warehouses: dict[int, Warehouse] = {}
            for warehouse, product_id, on_hand, reserved in rows:
                warehouses[warehouse.id] = warehouse
                if on_hand - reserved >= quantities[product_id]:
                    eligible.setdefault(warehouse.id, set()).add(product_id)
            return [
                WarehouseCandidate(
                    wid,
                    Coordinates(
                        latitude=warehouses[wid].latitude, longitude=warehouses[wid].longitude
                    ),
                )
                for wid, products in eligible.items()
                if len(products) == len(quantities)
            ]

    async def reserve(self, order_id: int, warehouse_id: int) -> bool:
        # One transaction per candidate: failed candidates leave no locks behind.
        async with self.session.begin():
            order = await self._order(order_id, lock=True)
            if order.status != "CREATED":
                return False
            items = await self._items(order_id)
            quantities = {i.product_id: i.quantity for i in items}
            # Shared locks permit parallel reservations while keeping the selected warehouse stable.
            warehouse = await self.session.scalar(
                select(Warehouse)
                .where(Warehouse.id == warehouse_id, Warehouse.deleted_at.is_(None))
                .with_for_update(read=True)
            )
            if warehouse is None:
                return False
            products = list(
                await self.session.scalars(
                    select(Product)
                    .where(Product.id.in_(quantities))
                    .order_by(Product.id)
                    .with_for_update(read=True)
                    .execution_options(populate_existing=True)
                )
            )
            if any(p.deleted_at is not None or not p.is_active for p in products):
                return False
            stocks = list(
                await self.session.scalars(
                    select(Stock)
                    .where(
                        Stock.warehouse_id == warehouse_id,
                        Stock.product_id.in_(quantities),
                        Stock.deleted_at.is_(None),
                    )
                    .order_by(Stock.product_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            if len(stocks) != len(quantities) or any(
                s.on_hand - s.reserved < quantities[s.product_id] for s in stocks
            ):
                return False
            for stock in stocks:
                stock.reserved += quantities[stock.product_id]
            order.warehouse_id = warehouse_id
            order.status = "BOOKED"
            return True

    async def ensure_customer(self, order_id: int, customer: CustomerDetails) -> None:
        async with self.session.begin():
            order = await self._order(order_id, lock=True)
            if order.customer_id is not None:
                return
            customer_row = await self.session.scalar(
                insert(Customer)
                .values(
                    first_name=customer.first_name,
                    last_name=customer.last_name,
                    phone=customer.phone,
                    email=customer.email,
                )
                .on_conflict_do_nothing(index_elements=[Customer.email])
                .returning(Customer.id)
            )
            if customer_row is None:
                customer_row = await self.session.scalar(
                    select(Customer.id).where(Customer.email == customer.email).with_for_update()
                )
            order.customer_id = customer_row

    async def cancel(self, order_id: int, reason: str) -> None:
        async with self.session.begin():
            order = await self._order(order_id, lock=True)
            if order.status not in ("CREATED", "BOOKED"):
                return
            if order.status == "BOOKED":
                quantities = {i.product_id: i.quantity for i in await self._items(order_id)}
                stocks = list(
                    await self.session.scalars(
                        select(Stock)
                        .where(
                            Stock.warehouse_id == order.warehouse_id,
                            Stock.product_id.in_(quantities),
                        )
                        .order_by(Stock.product_id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                )
                if len(stocks) != len(quantities) or any(
                    s.reserved < quantities[s.product_id] for s in stocks
                ):
                    raise RuntimeError("Order reservation is inconsistent; cannot release stock.")
                for stock in stocks:
                    stock.reserved -= quantities[stock.product_id]
            order.failure_reason = reason
            order.status = "CANCELLED"

    async def pay(self, order_id: int, payment_identifier: str | None = None) -> None:
        async with self.session.begin():
            order = await self._order(order_id, lock=True)
            if order.status == "BOOKED":
                order.payment_identifier = payment_identifier
                order.status = "PAID"

    async def get(self, order_id: int) -> OrderView:
        async with self.session.begin():
            # Shared order lock gives a consistent order/items/history read across statements.
            row = await self.session.scalar(
                select(Order)
                .where(Order.id == order_id)
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
            if row is None:
                raise OrderNotFound
            return await self._view(row)

    async def list(self, limit: int, offset: int) -> list[OrderView]:
        async with self.session.begin():
            rows = list(
                await self.session.scalars(
                    select(Order)
                    .order_by(Order.id.desc())
                    .limit(limit)
                    .offset(offset)
                    .with_for_update(read=True)
                    .execution_options(populate_existing=True)
                )
            )
            return [await self._view(row) for row in rows]
