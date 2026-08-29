"""Django repository for the product category directory."""

from hasta_la_vista_money import constants
from hasta_la_vista_money.receipts.models import ProductCategory
from hasta_la_vista_money.receipts.product_category_constants import (
    normalize_product_category_name,
)
from hasta_la_vista_money.users.models import User


class ProductCategoryRepository:
    """Persist normalized product categories and starter directories."""

    def get_or_create_category(
        self,
        *,
        user: User,
        name: str,
    ) -> ProductCategory:
        """Return a user's category with a normalized, unique name."""
        display_name = ' '.join(name.split())
        normalized_name = normalize_product_category_name(display_name)
        category, _ = ProductCategory.objects.get_or_create(
            user=user,
            normalized_name=normalized_name,
            defaults={'name': display_name},
        )
        return category

    def rename_category(self, category: ProductCategory, name: str) -> None:
        """Rename a category while preserving its normalized-name invariant."""
        category.name = ' '.join(name.split())
        category.normalized_name = normalize_product_category_name(
            category.name,
        )
        category.save(update_fields=['name', 'normalized_name'])

    def seed_starter_categories(self, user: User) -> None:
        """Create any missing standard product categories for a user."""
        for name in constants.STARTER_PRODUCT_CATEGORIES:
            self.get_or_create_category(user=user, name=name)
