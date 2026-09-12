import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.adapters.inbound.http.health import router
from app.adapters.inbound.http.orders import router as orders_router
from app.adapters.inbound.http.products import router as products_router
from app.adapters.inbound.http.warehouses import router as warehouses_router
from app.adapters.outbound.geocoding.mock import MockGeocoder
from app.adapters.outbound.payments.mock import MockPaymentGateway
from app.infrastructure.config import Settings
from app.infrastructure.database import create_engine, create_session_maker
from app.infrastructure.logging import RequestLoggingMiddleware, configure_logging

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    # Pyright cannot infer values supplied by Pydantic Settings from the environment.
    settings = settings if settings is not None else Settings()  # pyright: ignore[reportCallIssue]

    configure_logging(settings.log_level, settings.environment)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.session_maker = create_session_maker(engine)
        logger.info("application.started")
        try:
            yield
        finally:
            await engine.dispose()
            logger.info("application.stopped")

    app = FastAPI(title="Backend Assessment", lifespan=lifespan)

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error"},
            headers={"X-Request-ID": request.state.request_id},
        )

    app.state.order_geocoder = MockGeocoder()
    app.state.payment_gateway = MockPaymentGateway()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "Idempotency-Key"],
        expose_headers=["Location", "X-Request-ID"],
    )
    app.add_middleware(RequestLoggingMiddleware)
    app.include_router(router)
    app.include_router(orders_router)
    app.include_router(products_router)
    app.include_router(warehouses_router)
    return app
