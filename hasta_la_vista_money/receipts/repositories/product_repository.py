"""Django repository for Product model.

This module provides data access layer for Product model,
including filtering and CRUD operations.
"""

from django.db.models import QuerySet

from hasta_la_vista_money.receipts.models import Product


class ProductRepository:
    """Repository for Product model operations.

    Provides methods for accessing and manipulating product data.
    """

    def create_product(self, **kwargs: object) -> Product:
        """Create a new product.

        Args:
            **kwargs: Product field values (user, product_name, price,
                quantity, amount, etc.).

        Returns:
            Product: Created product instance.
        """
        return Product.objects.create(**kwargs)

    def bulk_create_products(
        self,
        products: list[Product],
    ) -> list[Product]:
        """Create multiple products in a single database query.

        Args:
            products: List of Product instances to create.

        Returns:
            list[Product]: List of created product instances.
        """
        return Product.objects.bulk_create(products)

    def filter(self, **kwargs: object) -> QuerySet[Product]:
        """Filter products by given criteria.

        Args:
            **kwargs: Filter criteria (field=value pairs).

        Returns:
            QuerySet[Product]: Filtered QuerySet.
        """
        return Product.objects.filter(**kwargs)
