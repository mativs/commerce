import logging

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.demo_data import WAREHOUSES, product_rows

logger = logging.getLogger(__name__)


async def reset_demo_data(session: AsyncSession) -> None:
    """Replace disposable assessment data; not a production administration operation.

    All statements share one transaction, committed only after reseeding succeeds.
    On failure, the request's session context closes and rolls back the transaction;
    the shared HTTP boundary logs the error and returns 500. Let errors propagate.
    """
    # Fixed table identifiers, with no request interpolation. Seed values below are bound.
    await session.execute(
        sa.text(
            "TRUNCATE TABLE order_validation_findings, "
            "order_validation_check_results, order_validation_runs, "
            "order_items, order_status_history, orders, customers, stock, "
            "audit_logs, products, warehouses RESTART IDENTITY CASCADE"
        )
    )
    await session.execute(
        sa.text(
            "INSERT INTO warehouses (name, latitude, longitude) "
            "VALUES (:name, :latitude, :longitude)"
        ),
        WAREHOUSES,
    )
    await session.execute(
        sa.text("INSERT INTO products (name, sku, ean, price) VALUES (:name, :sku, :ean, :price)"),
        [{key: value for key, value in row.items() if key != "currency"} for row in product_rows()],
    )
    await session.execute(
        sa.text(
            "INSERT INTO stock (warehouse_id, product_id, on_hand, reserved) "
            "SELECT w.id, p.id, (5 + (p.position * 7 + w.position * 13) % 46)::integer, 0 "
            "FROM (SELECT id, row_number() OVER (ORDER BY id) - 1 AS position FROM warehouses) w "
            "CROSS JOIN (SELECT id, row_number() OVER (ORDER BY sku, id) - 1 AS position "
            "FROM products WHERE is_active) p "
            "WHERE p.position < 2 OR (p.position + w.position) % 5 < 3 "
            "ORDER BY w.id, p.id"
        )
    )
    await session.commit()
    logger.info("demo_data.reset")
