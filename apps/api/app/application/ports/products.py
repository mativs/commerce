from typing import Protocol

from app.domain.products import ProductView


class ProductRepository(Protocol):
    async def list(
        self, limit: int, offset: int, query: str | None, is_active: bool | None
    ) -> list[ProductView]: ...

    async def get(self, product_id: int) -> ProductView: ...
