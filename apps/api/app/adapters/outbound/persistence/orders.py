import hashlib
import json
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select, text
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
        history = list(
            await self.session.scalars(
                select(OrderStatusHistory)
                .where(OrderStatusHistory.order_id == row.id)
                .order_by(OrderStatusHistory.created_at, OrderStatusHistory.id)
            )
        )
        customer = await self.session.get(Customer, row.customer_id)
        return self._make_view(row, customer, items, history)

    @staticmethod
    def _make_view(
        row: Order,
        customer: Customer | None,
        items: list[OrderItem],
        history: list[OrderStatusHistory] | tuple[OrderStatusHistory, ...],
    ) -> OrderView:
        return OrderView(
            id=row.id,
            status=row.status,
            shipping_address=row.shipping_address,
            latitude=row.latitude,
            longitude=row.longitude,
            warehouse_id=row.warehouse_id,
            warehouse_decision=row.warehouse_decision,
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
                if customer is not None
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
                if row is None:
                    raise RuntimeError("Order idempotency conflict without an existing order.")
                if row.request_hash != fingerprint:
                    raise IdempotencyConflict("This idempotency key belongs to a different order.")
                return await self._view(row), False
            if command.customer is not None:
                customer_id = await self.session.scalar(
                    insert(Customer)
                    .values(
                        first_name=command.customer.first_name,
                        last_name=command.customer.last_name,
                        phone=command.customer.phone,
                        email=command.customer.email,
                    )
                    .on_conflict_do_nothing(index_elements=[Customer.email])
                    .returning(Customer.id)
                )
                if customer_id is None:
                    customer_id = await self.session.scalar(
                        select(Customer.id)
                        .where(Customer.email == command.customer.email)
                        .with_for_update()
                    )
                row = await self._order(order_id)
                row.customer_id = customer_id
            product_ids = [item.product_id for item in command.items]
            # Shared locks preserve catalog price/eligibility until snapshots and total are saved.
            eligible_product_ids = list(
                await self.session.scalars(
                    select(Product.id)
                    .where(
                        Product.id.in_(product_ids),
                        Product.deleted_at.is_(None),
                        Product.is_active.is_(True),
                    )
                    .order_by(Product.id)
                    .with_for_update(read=True)
                )
            )
            if len(eligible_product_ids) != len(product_ids):
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
            required_products = (
                select(func.count())
                .select_from(OrderItem)
                .where(OrderItem.order_id == order_id)
                .scalar_subquery()
            )
            warehouses = list(
                await self.session.scalars(
                    select(Warehouse)
                    .join(Stock, Stock.warehouse_id == Warehouse.id)
                    .join(
                        OrderItem,
                        (OrderItem.product_id == Stock.product_id)
                        & (OrderItem.order_id == order_id),
                    )
                    .where(
                        Warehouse.deleted_at.is_(None),
                        Stock.on_hand - Stock.reserved >= OrderItem.quantity,
                    )
                    .group_by(Warehouse.id)
                    .having(func.count(func.distinct(Stock.product_id)) == required_products)
                )
            )
            return [
                WarehouseCandidate(
                    warehouse.id,
                    Coordinates(latitude=warehouse.latitude, longitude=warehouse.longitude),
                    warehouse.name,
                )
                for warehouse in warehouses
            ]

    async def record_warehouse_decision(
        self,
        order_id: int,
        coordinates: Coordinates,
        ranked: list[tuple[WarehouseCandidate, float]],
    ) -> None:
        async with self.session.begin():
            order = await self._order(order_id, lock=True)
            if order.status == "CREATED" and order.warehouse_decision is None:
                order.warehouse_decision = {
                    "version": 1,
                    "evaluated_at": datetime.now(UTC).isoformat(),
                    "strategy": "nearest_available_haversine_then_warehouse_id",
                    "shipping_coordinates": asdict(coordinates),
                    "selected_warehouse_id": None,
                    "candidates": [
                        {
                            "warehouse_id": candidate.id,
                            "warehouse_name": candidate.name,
                            "coordinates": asdict(candidate.coordinates),
                            "distance_km": distance,
                            "rank": rank,
                            "outcome": "NOT_ATTEMPTED",
                            "reason": None,
                        }
                        for rank, (candidate, distance) in enumerate(ranked, start=1)
                    ],
                }

    @staticmethod
    def _record_reservation(
        order: Order, warehouse_id: int, outcome: str, reason: str | None = None
    ) -> None:
        if order.warehouse_decision is None:
            return
        decision = deepcopy(order.warehouse_decision)
        for candidate in decision["candidates"]:
            if candidate["warehouse_id"] == warehouse_id:
                candidate["outcome"] = outcome
                candidate["reason"] = reason
                break
        if outcome == "SELECTED":
            decision["selected_warehouse_id"] = warehouse_id
        order.warehouse_decision = decision

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
                self._record_reservation(order, warehouse_id, "REJECTED", "WAREHOUSE_UNAVAILABLE")
                return False
            product_ids = list(
                await self.session.scalars(
                    select(Product.id)
                    .where(
                        Product.id.in_(quantities.keys()),
                        Product.deleted_at.is_(None),
                        Product.is_active.is_(True),
                    )
                    .order_by(Product.id)
                    .with_for_update(read=True)
                )
            )
            if len(product_ids) != len(quantities):
                self._record_reservation(order, warehouse_id, "REJECTED", "PRODUCT_UNAVAILABLE")
                return False
            stocks = list(
                await self.session.scalars(
                    select(Stock)
                    .where(
                        Stock.warehouse_id == warehouse_id,
                        Stock.product_id.in_(quantities),
                    )
                    .order_by(Stock.product_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            if len(stocks) != len(quantities) or any(
                s.on_hand - s.reserved < quantities[s.product_id] for s in stocks
            ):
                self._record_reservation(order, warehouse_id, "REJECTED", "INSUFFICIENT_STOCK")
                return False
            for stock in stocks:
                stock.reserved += quantities[stock.product_id]
            self._record_reservation(order, warehouse_id, "SELECTED")
            order.warehouse_id = warehouse_id
            order.status = "BOOKED"
            return True

    async def cancel(self, order_id: int, reason: str) -> None:
        async with self.session.begin():
            order = await self._order(order_id, lock=True)
            if order.status not in ("CREATED", "BOOKED", "PAYING"):
                return
            if order.status in ("BOOKED", "PAYING"):
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

    async def start_payment(self, order_id: int) -> None:
        async with self.session.begin():
            order = await self._order(order_id, lock=True)
            if order.status != "BOOKED":
                raise RuntimeError("Only a booked order can start payment.")
            order.status = "PAYING"

    async def pay(self, order_id: int, payment_identifier: str | None = None) -> None:
        async with self.session.begin():
            order = await self._order(order_id, lock=True)
            if order.status == "PAYING":
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
            # Batch hydration without row locks is safe because every statement below reads
            # from one PostgreSQL transaction snapshot. Locks would serialize each relation
            # read with writers and turn a paginated list into a lock-held N+1 read.
            await self.session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            rows = list(
                await self.session.scalars(
                    select(Order)
                    .order_by(Order.id.desc())
                    .limit(limit)
                    .offset(offset)
                    .execution_options(populate_existing=True)
                )
            )
            if not rows:
                return []

            order_ids = [row.id for row in rows]
            items = list(
                await self.session.scalars(
                    select(OrderItem)
                    .where(OrderItem.order_id.in_(order_ids))
                    .order_by(OrderItem.order_id, OrderItem.product_id)
                )
            )
            history = list(
                await self.session.scalars(
                    select(OrderStatusHistory)
                    .where(OrderStatusHistory.order_id.in_(order_ids))
                    .order_by(
                        OrderStatusHistory.order_id,
                        OrderStatusHistory.created_at,
                        OrderStatusHistory.id,
                    )
                )
            )
            customer_ids = {row.customer_id for row in rows if row.customer_id is not None}
            customers = {
                customer.id: customer
                for customer in await self.session.scalars(
                    select(Customer).where(Customer.id.in_(customer_ids))
                )
            }
            items_by_order: dict[int, list[OrderItem]] = {order_id: [] for order_id in order_ids}
            history_by_order: dict[int, list[OrderStatusHistory]] = {
                order_id: [] for order_id in order_ids
            }
            for item in items:
                items_by_order[item.order_id].append(item)
            for entry in history:
                history_by_order[entry.order_id].append(entry)
            return [
                self._make_view(
                    row,
                    customers.get(row.customer_id),
                    items_by_order[row.id],
                    history_by_order[row.id],
                )
                for row in rows if row is not None
            ]
