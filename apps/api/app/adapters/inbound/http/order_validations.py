from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.adapters.inbound.http.dependencies import DatabaseSession, PageLimit, PageOffset
from app.adapters.outbound.persistence.order_validation_checks import CHECKS
from app.adapters.outbound.persistence.order_validations import (
    SqlAlchemyOrderValidationRepository,
    ValidationConflict,
)

router = APIRouter(prefix="/order-validation-runs", tags=["order validations"])


class Thresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    created_age_seconds: int = Field(default=300, ge=1, le=604800)
    booked_age_seconds: int = Field(default=300, ge=1, le=604800)
    payment_age_seconds: int = Field(default=300, ge=1, le=604800)


class ValidationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checks: list[str] = Field(default_factory=lambda: list(CHECKS), min_length=1)
    thresholds: Thresholds = Field(default_factory=Thresholds)

    @field_validator("checks")
    @classmethod
    def known_checks(cls, checks: list[str]) -> list[str]:
        if any(code not in CHECKS for code in checks):
            raise ValueError("Unknown validation check")
        return sorted(set(checks))


@router.post("", status_code=201)
async def run_validations(
    data: ValidationInput,
    session: DatabaseSession,
    response: Response,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=128, pattern=r"^[!-~]+$")],
):
    parameters = data.model_dump()
    parameters["checks"] = sorted(parameters["checks"])
    try:
        result, created = await SqlAlchemyOrderValidationRepository(session).run(
            idempotency_key, parameters
        )
    except ValidationConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    response.status_code = 201 if created else 200
    response.headers["Location"] = f"/order-validation-runs/{result['id']}"
    return result


@router.get("")
async def list_runs(session: DatabaseSession, limit: PageLimit = 50, offset: PageOffset = 0):
    return await SqlAlchemyOrderValidationRepository(session).list(limit, offset)


@router.get("/{run_id}")
async def get_run(run_id: int, session: DatabaseSession):
    result = await SqlAlchemyOrderValidationRepository(session).get(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Validation run not found.")
    return result


@router.get("/{run_id}/findings")
async def list_findings(
    run_id: int,
    session: DatabaseSession,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
    check: str | None = None,
    severity: Literal["ERROR", "WARNING"] | None = None,
    order_id: int | None = None,
):
    repository = SqlAlchemyOrderValidationRepository(session)
    if await repository.get(run_id) is None:
        raise HTTPException(status_code=404, detail="Validation run not found.")
    return await repository.findings(run_id, limit, offset, check, severity, order_id)
