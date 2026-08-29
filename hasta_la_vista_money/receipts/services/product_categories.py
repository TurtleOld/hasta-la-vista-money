"""Operations for the product category directory."""

from core.repositories.protocols import ProductCategoryRepositoryProtocol
from hasta_la_vista_money.users.models import User


class ProductCategoryService:
    """Business operations for the product category directory."""

    def __init__(
        self,
        product_category_repository: ProductCategoryRepositoryProtocol,
    ) -> None:
        self.product_category_repository = product_category_repository

    def seed_starter_product_categories(self, user: User) -> None:
        """Create the standard product category directory for a user."""
        self.product_category_repository.seed_starter_categories(user)
