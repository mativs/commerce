from __future__ import annotations

import json
import logging
from time import monotonic

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.persistence.order_validation_checks import CHECKS

logger = logging.getLogger(__name__)

SEVERITY_COUNTS = """
    (SELECT count(*) FROM order_validation_findings f
     JOIN order_validation_check_results c ON c.id=f.check_result_id
     WHERE c.run_id=r.id AND f.severity='ERROR') AS error_count,
    (SELECT count(*) FROM order_validation_findings f
     JOIN order_validation_check_results c ON c.id=f.check_result_id
     WHERE c.run_id=r.id AND f.severity='WARNING') AS warning_count
"""


class ValidationConflict(Exception):
    pass


class SqlAlchemyOrderValidationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, run_id: int) -> dict | None:
        row = (
            (
                await self.session.execute(
                    text(
                        f"SELECT r.*, {SEVERITY_COUNTS} FROM order_validation_runs r WHERE r.id=:id"
                    ),
                    {"id": run_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        checks = (
            (
                await self.session.execute(
                    text(
                        "SELECT * FROM order_validation_check_results WHERE run_id=:id ORDER BY id"
                    ),
                    {"id": run_id},
                )
            )
            .mappings()
            .all()
        )
        return {
            **dict(row),
            "checks": [dict(c) for c in checks],
            "finding_count": sum(c["finding_count"] for c in checks),
        }

    async def list(self, limit: int, offset: int) -> list[dict]:
        rows = (
            await self.session.execute(
                text(
                    "SELECT r.*, (SELECT coalesce(sum(c.finding_count),0) "
                    "FROM order_validation_check_results c WHERE c.run_id=r.id) AS finding_count, "
                    f"{SEVERITY_COUNTS} "
                    "FROM order_validation_runs r ORDER BY r.id DESC LIMIT :limit OFFSET :offset"
                ),
                {"limit": limit, "offset": offset},
            )
        ).mappings()
        return [dict(r) for r in rows]

    async def findings(
        self,
        run_id: int,
        limit: int,
        offset: int,
        check: str | None,
        severity: str | None,
        order_id: int | None,
    ) -> list[dict]:
        rows = (
            await self.session.execute(
                text(
                    "SELECT f.*, c.check_code FROM order_validation_findings f "
                    "JOIN order_validation_check_results c ON c.id=f.check_result_id "
                    "WHERE c.run_id=:id "
                    "AND (CAST(:check AS text) IS NULL OR c.check_code=:check) "
                    "AND (CAST(:severity AS text) IS NULL OR f.severity=:severity) "
                    "AND (CAST(:order_id AS integer) IS NULL OR f.order_id=:order_id) "
                    "ORDER BY f.id LIMIT :limit OFFSET :offset"
                ),
                {
                    "id": run_id,
                    "limit": limit,
                    "offset": offset,
                    "check": check,
                    "severity": severity,
                    "order_id": order_id,
                },
            )
        ).mappings()
        return [dict(r) for r in rows]

    async def run(self, key: str, parameters: dict) -> tuple[dict, bool]:
        # This session holds only a transaction-scoped lock. A separate session
        # commits each result independently, so crashes do not erase prior output.
        async with self.session.begin():
            async with AsyncSession(bind=self.session.bind, expire_on_commit=False) as worker:
                async with worker.begin():
                    existing = (
                        (
                            await worker.execute(
                                text(
                                    "SELECT id, parameters FROM order_validation_runs WHERE "
                                    "idempotency_key=:key"
                                ),
                                {"key": key},
                            )
                        )
                        .mappings()
                        .first()
                    )
                    if existing:
                        if existing["parameters"] != parameters:
                            raise ValidationConflict(
                                "Idempotency key used with different parameters."
                            )
                        result = await SqlAlchemyOrderValidationRepository(worker).get(
                            existing["id"]
                        )
                        assert result is not None
                        return result, False
                locked = await self.session.scalar(
                    text("SELECT pg_try_advisory_xact_lock(hashtext(current_schema()), 192837)")
                )
                if not locked:
                    raise ValidationConflict("An order validation run is already executing.")
                # Recheck after acquiring the lock: another request may have just finished.
                async with worker.begin():
                    existing = (
                        (
                            await worker.execute(
                                text(
                                    "SELECT id, parameters FROM order_validation_runs WHERE "
                                    "idempotency_key=:key"
                                ),
                                {"key": key},
                            )
                        )
                        .mappings()
                        .first()
                    )
                    if existing:
                        if existing["parameters"] != parameters:
                            raise ValidationConflict(
                                "Idempotency key used with different parameters."
                            )
                        result = await SqlAlchemyOrderValidationRepository(worker).get(
                            existing["id"]
                        )
                        assert result is not None
                        return result, False
                    await worker.execute(
                        text(
                            "UPDATE order_validation_check_results SET status='FAILED', "
                            "finished_at=clock_timestamp(), error='Execution interrupted' "
                            "WHERE status IN ('PENDING','RUNNING') AND run_id IN "
                            "(SELECT id FROM order_validation_runs WHERE status='RUNNING')"
                        )
                    )
                    await worker.execute(
                        text(
                            "UPDATE order_validation_runs SET status='INTERRUPTED', "
                            "finished_at=clock_timestamp() WHERE status='RUNNING'"
                        )
                    )
                    run_id = await worker.scalar(
                        text(
                            "INSERT INTO order_validation_runs (idempotency_key,parameters,status) "
                            "VALUES (:key,CAST(:parameters AS jsonb),'RUNNING') RETURNING id"
                        ),
                        {"key": key, "parameters": json.dumps(parameters)},
                    )
                    as_of = await worker.scalar(text("SELECT clock_timestamp()"))
                    for code in parameters["checks"]:
                        await worker.execute(
                            text(
                                "INSERT INTO order_validation_check_results "
                                "(run_id,check_code,status) "
                                "VALUES (:id,:code,'PENDING')"
                            ),
                            {"id": run_id, "code": code},
                        )
                started = monotonic()
                failures = 0
                for code in parameters["checks"]:
                    if monotonic() - started >= 30:
                        async with worker.begin():
                            await worker.execute(
                                text(
                                    "UPDATE order_validation_check_results SET status='SKIPPED', "
                                    "finished_at=clock_timestamp(), error='Run time budget "
                                    "exhausted' "
                                    "WHERE run_id=:id AND status='PENDING'"
                                ),
                                {"id": run_id},
                            )
                        failures += 1
                        break
                    async with worker.begin():
                        check_id = await worker.scalar(
                            text(
                                "UPDATE order_validation_check_results SET status='RUNNING', "
                                "started_at=clock_timestamp() WHERE run_id=:id AND "
                                "check_code=:code "
                                "RETURNING id"
                            ),
                            {"id": run_id, "code": code},
                        )
                    query, severity = CHECKS[code]
                    try:
                        async with worker.begin():
                            await worker.execute(text("SET LOCAL statement_timeout='5s'"))
                            # INSERT ... SELECT keeps large finding sets in PostgreSQL.
                            # Missing entity columns are supplied by the row's JSON shape.
                            count = await worker.scalar(
                                text(
                                    "WITH inserted AS (INSERT INTO order_validation_findings "
                                    "(check_result_id,order_id,warehouse_id,"
                                    "product_id,severity,evidence) "
                                    "SELECT :check_id, (to_jsonb(q)->>'order_id')::integer, "
                                    "(to_jsonb(q)->>'warehouse_id')::integer, "
                                    "(to_jsonb(q)->>'product_id')::integer, :severity, q.evidence "
                                    f"FROM ({query}) q RETURNING id) SELECT count(*) FROM inserted"
                                ),
                                {
                                    "check_id": check_id,
                                    "severity": severity,
                                    "as_of": as_of,
                                    **parameters["thresholds"],
                                },
                            )
                            await worker.execute(
                                text(
                                    "UPDATE order_validation_check_results SET status='COMPLETED', "
                                    "finished_at=clock_timestamp(), finding_count=:count WHERE "
                                    "id=:id"
                                ),
                                {"id": check_id, "count": count},
                            )
                    except Exception:
                        logger.exception(
                            "order_validation.check_failed", extra={"check_code": code}
                        )
                        failures += 1
                        async with worker.begin():
                            await worker.execute(
                                text(
                                    "UPDATE order_validation_check_results SET status='FAILED', "
                                    "finished_at=clock_timestamp(), error='Check execution "
                                    "failed; see server logs' "
                                    "WHERE id=:id"
                                ),
                                {"id": check_id},
                            )
                async with worker.begin():
                    completed = await worker.scalar(
                        text(
                            "SELECT count(*) FROM order_validation_check_results "
                            "WHERE run_id=:id AND status='COMPLETED'"
                        ),
                        {"id": run_id},
                    )
                    status = "COMPLETED" if not failures else ("PARTIAL" if completed else "FAILED")
                    await worker.execute(
                        text(
                            "UPDATE order_validation_runs SET status=:status, "
                            "finished_at=clock_timestamp() WHERE id=:id"
                        ),
                        {"id": run_id, "status": status},
                    )
                    result = await SqlAlchemyOrderValidationRepository(worker).get(run_id)
                    assert result is not None
                    return result, True
