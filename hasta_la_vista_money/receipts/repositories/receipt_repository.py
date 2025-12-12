"""Django repository for Receipt model.

This module provides data access layer for Receipt model,
including filtering, aggregation, and CRUD operations.
"""

from datetime import datetime
from typing import Any

from django.db.models import QuerySet, Sum
from django.db.models.functions import TruncMonth

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import Product, Receipt
from hasta_la_vista_money.users.models import User


class ReceiptRepository:
    """Repository for Receipt model operations.

    Provides methods for accessing and manipulating receipt data,
    including filtering by user, date ranges, and account.
    """

    def get_by_id(self, receipt_id: int) -> Receipt:
        """Get receipt by ID.

        Args:
            receipt_id: ID of the receipt to retrieve.

        Returns:
            Receipt: Receipt instance.

        Raises:
            Receipt.DoesNotExist: If receipt with given ID doesn't exist.
        """
        return Receipt.objects.get(pk=receipt_id)

    def get_by_user(self, user: User) -> QuerySet[Receipt]:
        """Get all receipts for a user.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[Receipt]: QuerySet of user's receipts.
        """
        return Receipt.objects.for_user(user)

    def get_by_users(self, users: list[User]) -> QuerySet[Receipt]:
        """Get all receipts for a list of users.

        Args:
            users: List of User instances to filter by.

        Returns:
            QuerySet[Receipt]: QuerySet of receipts for specified users.
        """
        return Receipt.objects.for_users(users)

    def get_by_user_with_related(self, user: User) -> QuerySet[Receipt]:
        """Get all receipts for a user with related objects optimized.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[Receipt]: QuerySet with select_related and prefetch_related
                optimizations applied.
        """
        return Receipt.objects.for_user(user).with_related()

    def get_by_users_with_related(
        self,
        users: list[User],
    ) -> QuerySet[Receipt]:
        """Get all receipts for users with related objects optimized.

        Args:
            users: List of User instances to filter by.

        Returns:
            QuerySet[Receipt]: QuerySet with select_related and prefetch_related
                optimizations applied.
        """
        return Receipt.objects.for_users(users).with_related()

    def get_by_user_and_number(
        self,
        user: User,
        number_receipt: int | None,
    ) -> QuerySet[Receipt]:
        """Get receipts by user and receipt number.

        Args:
            user: User instance to filter by.
            number_receipt: Receipt number to filter by.

        Returns:
            QuerySet[Receipt]: Filtered QuerySet.
        """
        return Receipt.objects.for_user_and_number(user, number_receipt)

    def add_product_to_receipt(
        self,
        receipt: Receipt,
        product: 'Product',
    ) -> None:
        """Add product to receipt.

        Args:
            receipt: Receipt instance to add product to.
            product: Product instance to add.
        """
        receipt.product.add(product)

    def create_receipt(self, **kwargs: object) -> Receipt:
        """Create a new receipt.

        Args:
            **kwargs: Receipt field values (user, account, seller,
                receipt_date, total_sum, etc.).

        Returns:
            Receipt: Created receipt instance.
        """
        return Receipt.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[Receipt]:
        """Filter receipts by given criteria.

        Args:
            **kwargs: Filter criteria (field=value pairs).

        Returns:
            QuerySet[Receipt]: Filtered QuerySet.
        """
        return Receipt.objects.filter(**kwargs)

    def filter_by_account_and_date_range(
        self,
        account: Account,
        start_date: datetime,
        end_date: datetime,
    ) -> QuerySet[Receipt, dict[str, Any]]:
        """Filter receipts by account and date range.

        Returns aggregated data grouped by month and operation type.

        Args:
            account: Account instance to filter by.
            start_date: Start of date range (inclusive).
            end_date: End of date range (inclusive).

        Returns:
            QuerySet[Receipt, dict[str, Any]]: Aggregated QuerySet with
                month, operation_type, and total fields.
        """
        return (
            Receipt.objects.filter(
                account=account,
                receipt_date__gte=start_date,
                receipt_date__lte=end_date,
            )
            .annotate(month=TruncMonth('receipt_date'))
            .values('month', 'operation_type')
            .annotate(total=Sum('total_sum'))
        )
