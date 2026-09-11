from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.adapters.inbound.http.dependencies import DatabaseSession
from app.adapters.inbound.http.health import router
from app.adapters.inbound.http.products import router as products_router
from app.adapters.inbound.http.shipping_addresses import get_shipping_address_service
from app.adapters.inbound.http.shipping_addresses import router as shipping_addresses_router
from app.adapters.inbound.http.warehouses import router as warehouses_router
from app.adapters.outbound.geocoding.mock import MockGeocoder
from app.adapters.outbound.persistence.shipping_addresses import SqlAlchemyShippingAddressRepository
from app.application.ports.geocoder import GeocodingUnavailable
from app.application.services.shipping_addresses import ShippingAddressService
from app.domain.shipping_address import ShippingAddressNotFound
from app.infrastructure.config import Settings
from app.infrastructure.database import create_engine, create_session_maker


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.session_maker = create_session_maker(engine)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="Backend Assessment", lifespan=lifespan)
    app.state.geocoder = MockGeocoder()

    def shipping_address_service(session: DatabaseSession) -> ShippingAddressService:
        return ShippingAddressService(
            SqlAlchemyShippingAddressRepository(session), app.state.geocoder
        )

    app.dependency_overrides[get_shipping_address_service] = shipping_address_service

    @app.exception_handler(ShippingAddressNotFound)
    async def address_not_found(request: Request, error: ShippingAddressNotFound):
        return JSONResponse(status_code=404, content={"detail": "Shipping address not found."})

    @app.exception_handler(GeocodingUnavailable)
    async def geocoding_unavailable(request: Request, error: GeocodingUnavailable):
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Could not locate this address. No changes were saved. Please try again."
            },
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )
    app.include_router(router)
    app.include_router(products_router)
    app.include_router(warehouses_router)
    app.include_router(shipping_addresses_router)
    return app
