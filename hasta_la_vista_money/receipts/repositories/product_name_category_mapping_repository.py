"""Django repository for pinned product-name-to-category mappings."""

from django.core.exceptions import ValidationError

from hasta_la_vista_money.receipts.models import (
    ProductCategory,
    ProductNameCategoryMapping,
)
from hasta_la_vista_money.users.models import User


class ProductNameCategoryMappingRepository:
    """Persist pinned product-name-to-category mappings for one user."""

    def upsert(
        self,
        *,
        user: User,
        normalized_product_name: str,
        category: ProductCategory,
    ) -> ProductNameCategoryMapping:
        """Create or update the pinned mapping for a normalized name.

        Args:
            user: Owner of the mapping.
            normalized_product_name: Canonical form of the product name.
            category: Category the name is pinned to.

        Returns:
            The created or updated mapping.

        Raises:
            ValidationError: If the category belongs to another user.
        """
        if user.pk != category.user_id:
            raise ValidationError(
                'Mapping category must belong to the mapping owner.',
            )
        mapping, _ = ProductNameCategoryMapping.objects.update_or_create(
            user=user,
            normalized_product_name=normalized_product_name,
            defaults={'category': category},
        )
        return mapping

    def repoint_category(
        self,
        *,
        user: User,
        from_category: ProductCategory,
        to_category: ProductCategory,
    ) -> None:
        """Move mappings to another category, dropping name collisions."""
        mappings = ProductNameCategoryMapping.objects.filter(
            user=user,
            category=from_category,
        )
        for mapping in mappings:
            collision = (
                ProductNameCategoryMapping.objects.filter(
                    user=user,
                    normalized_product_name=mapping.normalized_product_name,
                    category=to_category,
                )
                .exclude(pk=mapping.pk)
                .exists()
            )
            if collision:
                mapping.delete()
            else:
                mapping.category = to_category
                mapping.save(update_fields=['category'])
