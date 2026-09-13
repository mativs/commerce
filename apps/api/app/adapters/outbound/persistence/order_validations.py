from __future__ import annotations

import logging
from time import monotonic

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.persistence.models import (
    OrderValidationCheckResult,
    OrderValidationFinding,
    OrderValidationRun,
)
from app.adapters.outbound.persistence.order_validation_checks import CHECKS

logger = logging.getLogger(__name__)


class ValidationConflict(Exception):
    pass


class SqlAlchemyOrderValidationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _model_dict(model) -> dict:
        return {column.name: getattr(model, column.name) for column in model.__table__.columns}

    @staticmethod
    def _severity_count(severity: str):
        return (
            select(func.count(OrderValidationFinding.id))
            .join(
                OrderValidationCheckResult,
                OrderValidationCheckResult.id == OrderValidationFinding.check_result_id,
            )
            .where(
                OrderValidationCheckResult.run_id == OrderValidationRun.id,
                OrderValidationFinding.severity == severity,
            )
            .correlate(OrderValidationRun)
            .scalar_subquery()
        )

    async def _find_by_key(self, session: AsyncSession, key: str) -> OrderValidationRun | None:
        return await session.scalar(
            select(OrderValidationRun).where(OrderValidationRun.idempotency_key == key)
        )

    async def get(self, run_id: int) -> dict | None:
        row = (
            await self.session.execute(
                select(
                    OrderValidationRun,
                    self._severity_count("ERROR").label("error_count"),
                    self._severity_count("WARNING").label("warning_count"),
                ).where(OrderValidationRun.id == run_id)
            )
        ).first()
        if row is None:
            return None

        run, error_count, warning_count = row
        checks = list(
            await self.session.scalars(
                select(OrderValidationCheckResult)
                .where(OrderValidationCheckResult.run_id == run_id)
                .order_by(OrderValidationCheckResult.id)
            )
        )
        return {
            **self._model_dict(run),
            "error_count": error_count,
            "warning_count": warning_count,
            "checks": [self._model_dict(check) for check in checks],
            "finding_count": sum(check.finding_count for check in checks),
        }

    async def list(self, limit: int, offset: int) -> list[dict]:
        finding_count = (
            select(func.coalesce(func.sum(OrderValidationCheckResult.finding_count), 0))
            .where(OrderValidationCheckResult.run_id == OrderValidationRun.id)
            .correlate(OrderValidationRun)
            .scalar_subquery()
        )
        rows = await self.session.execute(
            select(
                OrderValidationRun,
                finding_count.label("finding_count"),
                self._severity_count("ERROR").label("error_count"),
                self._severity_count("WARNING").label("warning_count"),
            )
            .order_by(OrderValidationRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [
            {
                **self._model_dict(run),
                "finding_count": finding_count_value,
                "error_count": error_count,
                "warning_count": warning_count,
            }
            for run, finding_count_value, error_count, warning_count in rows
        ]

    async def findings(
        self,
        run_id: int,
        limit: int,
        offset: int,
        check: str | None,
        severity: str | None,
        order_id: int | None,
    ) -> list[dict]:
        conditions = [OrderValidationCheckResult.run_id == run_id]
        if check is not None:
            conditions.append(OrderValidationCheckResult.check_code == check)
        if severity is not None:
            conditions.append(OrderValidationFinding.severity == severity)
        if order_id is not None:
            conditions.append(OrderValidationFinding.order_id == order_id)

        rows = await self.session.execute(
            select(OrderValidationFinding, OrderValidationCheckResult.check_code)
            .join(
                OrderValidationCheckResult,
                OrderValidationCheckResult.id == OrderValidationFinding.check_result_id,
            )
            .where(*conditions)
            .order_by(OrderValidationFinding.id)
            .limit(limit)
            .offset(offset)
        )
        return [
            {**self._model_dict(finding), "check_code": check_code} for finding, check_code in rows
        ]

    async def run(self, key: str, parameters: dict) -> tuple[dict, bool]:
        # This session holds only a transaction-scoped lock. A separate session
        # commits each result independently, so crashes do not erase prior output.
        async with self.session.begin():
            async with AsyncSession(bind=self.session.bind, expire_on_commit=False) as worker:
                async with worker.begin():
                    existing = await self._find_by_key(worker, key)
                    if existing:
                        if existing.parameters != parameters:
                            raise ValidationConflict(
                                "Idempotency key used with different parameters."
                            )
                        result = await SqlAlchemyOrderValidationRepository(worker).get(existing.id)
                        assert result is not None
                        return result, False

                locked = await self.session.scalar(
                    text("SELECT pg_try_advisory_xact_lock(hashtext(current_schema()), 192837)")
                )
                if not locked:
                    raise ValidationConflict("An order validation run is already executing.")

                # Recheck after acquiring the lock: another request may have just finished.
                async with worker.begin():
                    existing = await self._find_by_key(worker, key)
                    if existing:
                        if existing.parameters != parameters:
                            raise ValidationConflict(
                                "Idempotency key used with different parameters."
                            )
                        result = await SqlAlchemyOrderValidationRepository(worker).get(existing.id)
                        assert result is not None
                        return result, False

                    await worker.execute(
                        update(OrderValidationCheckResult)
                        .where(
                            OrderValidationCheckResult.status.in_(["PENDING", "RUNNING"]),
                            OrderValidationCheckResult.run_id.in_(
                                select(OrderValidationRun.id).where(
                                    OrderValidationRun.status == "RUNNING"
                                )
                            ),
                        )
                        .values(
                            status="FAILED",
                            finished_at=func.clock_timestamp(),
                            error="Execution interrupted",
                        )
                    )
                    await worker.execute(
                        update(OrderValidationRun)
                        .where(OrderValidationRun.status == "RUNNING")
                        .values(status="INTERRUPTED", finished_at=func.clock_timestamp())
                    )

                    validation_run = OrderValidationRun(
                        idempotency_key=key,
                        parameters=parameters,
                        status="RUNNING",
                    )
                    worker.add(validation_run)
                    await worker.flush()
                    run_id = validation_run.id
                    as_of = await worker.scalar(select(func.clock_timestamp()))
                    worker.add_all(
                        [
                            OrderValidationCheckResult(
                                run_id=run_id,
                                check_code=code,
                                status="PENDING",
                            )
                            for code in parameters["checks"]
                        ]
                    )

                started = monotonic()
                failures = 0
                for code in parameters["checks"]:
                    if monotonic() - started >= 30:
                        async with worker.begin():
                            await worker.execute(
                                update(OrderValidationCheckResult)
                                .where(
                                    OrderValidationCheckResult.run_id == run_id,
                                    OrderValidationCheckResult.status == "PENDING",
                                )
                                .values(
                                    status="SKIPPED",
                                    finished_at=func.clock_timestamp(),
                                    error="Run time budget exhausted",
                                )
                            )
                        failures += 1
                        break

                    async with worker.begin():
                        check_id = await worker.scalar(
                            update(OrderValidationCheckResult)
                            .where(
                                OrderValidationCheckResult.run_id == run_id,
                                OrderValidationCheckResult.check_code == code,
                            )
                            .values(status="RUNNING", started_at=func.clock_timestamp())
                            .returning(OrderValidationCheckResult.id)
                        )

                    check = CHECKS[code]
                    query_parameters = {"as_of": as_of, **check.parameters}
                    if check.threshold_key is not None:
                        query_parameters["threshold_seconds"] = parameters["thresholds"][
                            check.threshold_key
                        ]
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
                                    f"FROM ({check.query.text}) q RETURNING id) "
                                    "SELECT count(*) FROM inserted"
                                ),
                                {
                                    "check_id": check_id,
                                    "severity": check.severity,
                                    **query_parameters,
                                },
                            )
                            await worker.execute(
                                update(OrderValidationCheckResult)
                                .where(OrderValidationCheckResult.id == check_id)
                                .values(
                                    status="COMPLETED",
                                    finished_at=func.clock_timestamp(),
                                    finding_count=count,
                                )
                            )
                    except Exception:
                        logger.exception(
                            "order_validation.check_failed", extra={"check_code": code}
                        )
                        failures += 1
                        async with worker.begin():
                            await worker.execute(
                                update(OrderValidationCheckResult)
                                .where(OrderValidationCheckResult.id == check_id)
                                .values(
                                    status="FAILED",
                                    finished_at=func.clock_timestamp(),
                                    error="Check execution failed; see server logs",
                                )
                            )

                async with worker.begin():
                    completed = await worker.scalar(
                        select(func.count())
                        .select_from(OrderValidationCheckResult)
                        .where(
                            OrderValidationCheckResult.run_id == run_id,
                            OrderValidationCheckResult.status == "COMPLETED",
                        )
                    )
                    status = "COMPLETED" if not failures else ("PARTIAL" if completed else "FAILED")
                    await worker.execute(
                        update(OrderValidationRun)
                        .where(OrderValidationRun.id == run_id)
                        .values(status=status, finished_at=func.clock_timestamp())
                    )
                    result = await SqlAlchemyOrderValidationRepository(worker).get(run_id)
                    assert result is not None
                    return result, True
