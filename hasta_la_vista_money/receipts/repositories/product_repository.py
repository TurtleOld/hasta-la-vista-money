"""Django repository for Product model.

This module provides data access layer for Product model,
including filtering and CRUD operations.
"""

from django.core.exceptions import ValidationError
from django.db.models import QuerySet

from hasta_la_vista_money import constants
from hasta_la_vista_money.receipts.models import (
    Product,
    ProductCategory,
    ProductCategorySource,
)
from hasta_la_vista_money.receipts.product_category_constants import (
    normalize_product_category_name,
)
from hasta_la_vista_money.users.models import User


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
        user = kwargs.get('user')
        category = kwargs.get('category')
        if (
            isinstance(user, User)
            and isinstance(category, ProductCategory)
            and user.pk != category.user_id
        ):
            raise ValidationError(
                'Product category must belong to the product owner.',
            )
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

    def get_external_category_candidate(
        self,
        product_id: int,
    ) -> Product | None:
        """Return an unresolved automatically categorized product."""
        return (
            Product.objects.filter(
                pk=product_id,
                category__normalized_name=(
                    normalize_product_category_name(
                        constants.DEFAULT_PRODUCT_CATEGORY,
                    )
                ),
                category_source=ProductCategorySource.WRITING_MATCH,
            )
            .select_related('user', 'category')
            .first()
        )
