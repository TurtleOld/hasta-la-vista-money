"""Django repository for Product model.

This module provides data access layer for Product model,
including filtering and CRUD operations.
"""

from collections.abc import Iterable

from django.core.exceptions import ValidationError
from django.db.models import Count, QuerySet

from hasta_la_vista_money import constants
from hasta_la_vista_money.receipts.models import (
    Product,
    ProductCategory,
    ProductCategorySource,
)
from hasta_la_vista_money.receipts.product_category_constants import (
    normalize_product_category_name,
    normalize_product_name,
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

    def reclassify_by_normalized_name(
        self,
        *,
        user: User,
        normalized_product_name: str,
        category: ProductCategory,
        source: ProductCategorySource,
        exclude_ids: Iterable[int] = (),
    ) -> int:
        """Reclassify the owner's non-manual rows with a normalized name.

        Applies the given category and source to every product row of the
        owner whose normalized name matches, leaving manual rows and the
        supplied ids untouched.

        Args:
            user: Owner of the products.
            normalized_product_name: Canonical form to match against.
            category: Category to assign to matching rows.
            source: Category source to assign to matching rows.
            exclude_ids: Product primary keys to leave untouched.

        Returns:
            Number of product rows updated.
        """
        products = Product.objects.filter(user=user).exclude(
            category_source=ProductCategorySource.MANUAL,
        )
        excluded = list(exclude_ids)
        if excluded:
            products = products.exclude(pk__in=excluded)

        updated = 0
        for product in products.iterator():
            if (
                normalize_product_name(product.product_name)
                != normalized_product_name
            ):
                continue
            product.category = category
            product.category_source = source
            product.save(update_fields=['category', 'category_source'])
            updated += 1
        return updated

    def move_category(
        self,
        *,
        user: User,
        from_category: ProductCategory,
        to_category: ProductCategory,
    ) -> int:
        """Reassign the owner's product rows from one category to another."""
        return Product.objects.filter(
            user=user,
            category=from_category,
        ).update(category=to_category)

    def count_by_categories(
        self,
        *,
        user: User,
        categories: Iterable[ProductCategory],
    ) -> dict[int, int]:
        """Return product counts keyed by category primary key."""
        rows = (
            Product.objects.filter(user=user, category__in=list(categories))
            .values('category')
            .annotate(count=Count('id'))
        )
        return {row['category']: row['count'] for row in rows}
