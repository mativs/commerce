from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.adapters.inbound.http.dependencies import DatabaseSession
from app.application.services.demo_reset import reset_demo_data

router = APIRouter(prefix="/demo", tags=["demo"])


class DemoResetRequest(BaseModel):
    confirmation: Literal["RESET"]


@router.post("/reset", status_code=204)
async def reset_demo(payload: DemoResetRequest, session: DatabaseSession) -> None:
    await reset_demo_data(session)
