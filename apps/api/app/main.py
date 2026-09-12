from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.adapters.inbound.http.health import router
from app.adapters.inbound.http.orders import router as orders_router
from app.adapters.inbound.http.products import router as products_router
from app.adapters.inbound.http.warehouses import router as warehouses_router
from app.adapters.outbound.geocoding.mock import MockGeocoder
from app.adapters.outbound.payments.mock import MockPaymentGateway
from app.infrastructure.config import Settings
from app.infrastructure.database import create_engine, create_session_maker


def create_app(settings: Settings | None = None) -> FastAPI:
    # Pyright cannot infer values supplied by Pydantic Settings from the environment.
    settings = settings if settings is not None else Settings()  # pyright: ignore[reportCallIssue]

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.session_maker = create_session_maker(engine)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="Backend Assessment", lifespan=lifespan)
    app.state.order_geocoder = MockGeocoder(simulate_failures=True)
    app.state.payment_gateway = MockPaymentGateway()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "Idempotency-Key"],
        expose_headers=["Location"],
    )
    app.include_router(router)
    app.include_router(orders_router)
    app.include_router(products_router)
    app.include_router(warehouses_router)
    return app
