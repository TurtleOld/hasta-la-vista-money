"""Django repository for Seller model.

This module provides data access layer for Seller model,
including filtering and CRUD operations.
"""

from django.db.models import QuerySet

from hasta_la_vista_money.receipts.models import Seller
from hasta_la_vista_money.users.models import User


class SellerRepository:
    """Repository for Seller model operations.

    Provides methods for accessing and manipulating seller data.
    """

    def update_or_create_seller(
        self,
        user: User,
        name_seller: str,
        defaults: dict[str, object] | None = None,
    ) -> Seller:
        """Create or update seller.

        Args:
            user: User instance who owns the seller.
            name_seller: Name of the seller.
            defaults: Dictionary of field values to update if seller exists.

        Returns:
            Seller: Seller instance (created or updated).
        """
        seller, _ = Seller.objects.update_or_create(
            user=user,
            name_seller=name_seller,
            defaults=defaults or {},
        )
        return seller

    def get_by_user(self, user: User) -> QuerySet[Seller]:
        """Get all sellers for a user.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[Seller]: QuerySet of user's sellers.
        """
        return Seller.objects.for_user(user)

    def get_by_users(self, users: list[User]) -> QuerySet[Seller]:
        """Get all sellers for a list of users.

        Args:
            users: List of User instances to filter by.

        Returns:
            QuerySet[Seller]: QuerySet of sellers for specified users.
        """
        return Seller.objects.for_users(users)

    def unique_by_name_for_user(self, user: User) -> QuerySet[Seller]:
        """Get unique sellers by name for a user.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[Seller]: QuerySet with unique sellers by name.
        """
        return Seller.objects.unique_by_name_for_user(user)

    def unique_by_name_for_users(self, users: list[User]) -> QuerySet[Seller]:
        """Get unique sellers by name for multiple users.

        Args:
            users: List of User instances to filter by.

        Returns:
            QuerySet[Seller]: QuerySet with unique sellers by name.
        """
        return Seller.objects.unique_by_name_for_users(users)

    def filter(self, **kwargs: object) -> QuerySet[Seller]:
        """Filter sellers by given criteria.

        Args:
            **kwargs: Filter criteria (field=value pairs).

        Returns:
            QuerySet[Seller]: Filtered QuerySet.
        """
        return Seller.objects.filter(**kwargs)
