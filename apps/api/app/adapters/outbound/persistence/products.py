from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.persistence.models import Product, Stock, Warehouse
from app.domain.products import ProductNotFound, ProductView, StockView


class SqlAlchemyProductRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _view(product: Product, stock: list[StockView]) -> ProductView:
        return ProductView(
            name=product.name,
            sku=product.sku,
            description=product.description,
            price=product.price,
            is_active=product.is_active,
            ean=product.ean,
            id=product.id,
            created_at=product.created_at,
            updated_at=product.updated_at,
            deleted_at=product.deleted_at,
            stock=stock,
        )

    @staticmethod
    def _stock_view(stock: Stock, warehouse_name: str) -> StockView:
        return StockView(
            warehouse_id=stock.warehouse_id,
            warehouse_name=warehouse_name,
            on_hand=stock.on_hand,
            reserved=stock.reserved,
            available=stock.on_hand - stock.reserved,
        )

    async def _products_with_stock(self, query, limit: int, offset: int):
        # Paginate products before joining stock so warehouse rows cannot move a product
        # to a different page.
        page = query.order_by(Product.id).limit(limit).offset(offset).subquery("product_page")
        statement = (
            select(Product, Stock, Warehouse.name)
            .join(page, Product.id == page.c.id)
            .outerjoin(Stock, Stock.product_id == Product.id)
            .outerjoin(
                Warehouse,
                and_(
                    Warehouse.id == Stock.warehouse_id,
                    Warehouse.deleted_at.is_(None),
                ),
            )
            .order_by(Product.id, Warehouse.id)
        )
        return (await self.session.execute(statement)).tuples().all()

    async def list(
        self, limit: int, offset: int, query: str | None, is_active: bool | None
    ) -> list[ProductView]:
        async with self.session.begin():
            statement = select(Product).where(Product.deleted_at.is_(None))
            if query and query.strip():
                value = query.strip()
                statement = statement.where(
                    or_(
                        Product.name.icontains(value, autoescape=True),
                        Product.sku.icontains(value, autoescape=True),
                    )
                )
            if is_active is not None:
                statement = statement.where(Product.is_active == is_active)
            rows = await self._products_with_stock(statement, limit, offset)
            grouped: dict[int, tuple[Product, list[StockView]]] = {}
            for product, stock, warehouse_name in rows:
                entry = grouped.setdefault(product.id, (product, []))
                if stock is not None and warehouse_name is not None:
                    entry[1].append(self._stock_view(stock, warehouse_name))
            return [self._view(product, stock) for product, stock in grouped.values()]

    async def get(self, product_id: int) -> ProductView:
        async with self.session.begin():
            product = await self.session.scalar(
                select(Product).where(
                    Product.id == product_id,
                    Product.deleted_at.is_(None),
                )
            )
            if product is None:
                raise ProductNotFound
            rows = (
                (
                    await self.session.execute(
                        select(Stock, Warehouse.name)
                        .join(Warehouse, Warehouse.id == Stock.warehouse_id)
                        .where(
                            Stock.product_id == product.id,
                            Warehouse.deleted_at.is_(None),
                        )
                        .order_by(Warehouse.id)
                    )
                )
                .tuples()
                .all()
            )
            stock = [self._stock_view(item, name) for item, name in rows]
            return self._view(product, stock)
