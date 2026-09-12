import asyncio
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from test_seed_migration import apply_seed


def run_migration(connection, filename):
    path = Path(__file__).parents[1] / "migrations/versions" / filename
    spec = importlib.util.spec_from_file_location("stock_seed_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        module.upgrade()


def test_stock_seed_distribution_audit_and_existing_balances(database_client):
    client, sessions = database_client

    async def check():
        await apply_seed(sessions)
        async with sessions() as session, session.begin():
            await session.execute(
                text("SELECT set_config('search_path', current_schema() || ',public', true)")
            )
            connection = await session.connection()
            await connection.run_sync(run_migration, "0006_stock.py")
            await connection.run_sync(run_migration, "0010_seed_stock.py")
            rows = (
                await session.execute(
                    text(
                        "SELECT warehouse_id, product_id, on_hand, reserved FROM stock ORDER BY id"
                    )
                )
            ).all()
            assert len(rows) == 320
            assortments = {}
            for warehouse_id, product_id, on_hand, reserved in rows:
                assortments.setdefault(warehouse_id, set()).add(product_id)
                assert 5 <= on_hand <= 50 and reserved == 0
            assert len(assortments) == 5
            assert {len(products) for products in assortments.values()} == {64}
            assert len({frozenset(products) for products in assortments.values()}) == 5
            assert len(set.union(*assortments.values())) == 100
            assert len(set.intersection(*assortments.values())) == 10
            assert len({row.on_hand for row in rows}) > 10
            assert (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM audit_logs "
                        "WHERE table_name='stock' AND action='create'"
                    )
                )
                == 320
            )
            # Reapplication must neither replenish used inventory nor revive deleted balances.
            await session.execute(
                text(
                    "UPDATE stock SET on_hand=7, reserved=3, deleted_at=clock_timestamp() "
                    "WHERE id=(SELECT min(id) FROM stock)"
                )
            )
            before = (await session.execute(text("SELECT * FROM stock ORDER BY id"))).all()
            logs_before = await session.scalar(text("SELECT count(*) FROM audit_logs"))
            await connection.run_sync(run_migration, "0010_seed_stock.py")
            assert (await session.execute(text("SELECT * FROM stock ORDER BY id"))).all() == before
            assert await session.scalar(text("SELECT count(*) FROM audit_logs")) == logs_before

    asyncio.run(check())
