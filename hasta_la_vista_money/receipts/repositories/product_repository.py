"""Django репозиторий для Product модели."""

from django.db.models import QuerySet

from hasta_la_vista_money.receipts.models import Product


class ProductRepository:
    """Репозиторий для работы с Product моделью."""

    def create_product(self, **kwargs: object) -> Product:
        """Создать новый продукт."""
        return Product.objects.create(**kwargs)

    def bulk_create_products(
        self,
        products: list[Product],
    ) -> list[Product]:
        """Создать несколько продуктов."""
        return Product.objects.bulk_create(products)

    def filter(self, **kwargs: object) -> QuerySet[Product]:
        """Фильтровать продукты."""
        return Product.objects.filter(**kwargs)
