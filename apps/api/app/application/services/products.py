from app.application.ports.products import ProductRepository
from app.domain.products import ProductView


class ProductService:
    def __init__(self, repository: ProductRepository):
        self.repository = repository

    async def list(
        self, limit: int, offset: int, query: str | None, is_active: bool | None
    ) -> list[ProductView]:
        return await self.repository.list(limit, offset, query, is_active)

    async def get(self, product_id: int) -> ProductView:
        return await self.repository.get(product_id)
