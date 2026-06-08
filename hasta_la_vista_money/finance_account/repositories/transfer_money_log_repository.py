"""Django repository for TransferMoneyLog model.

This module provides data access layer for TransferMoneyLog model,
including filtering by user and date ranges.
"""

from datetime import date

from django.db.models import QuerySet

from hasta_la_vista_money.finance_account.models import TransferMoneyLog
from hasta_la_vista_money.users.models import User


class TransferMoneyLogRepository:
    """Repository for TransferMoneyLog model operations.

    Provides methods for accessing and manipulating transfer money log data.
    """

    def get_by_id(self, log_id: int) -> TransferMoneyLog:
        """Get transfer log by ID.

        Args:
            log_id: ID of the log to retrieve.

        Returns:
            TransferMoneyLog: Transfer log instance.

        Raises:
            TransferMoneyLog.DoesNotExist: If log with given ID doesn't exist.
        """
        return TransferMoneyLog.objects.get(pk=log_id)

    def get_by_id_for_user(
        self,
        log_id: int,
        user: User,
        *,
        for_update: bool = False,
    ) -> TransferMoneyLog:
        """Get transfer log by ID for a user.

        Args:
            log_id: ID of the log to retrieve.
            user: Owner of the transfer log.
            for_update: Whether to lock the row for an atomic mutation.

        Returns:
            TransferMoneyLog: Transfer log instance.

        Raises:
            TransferMoneyLog.DoesNotExist: If log doesn't exist for user.
        """
        queryset = TransferMoneyLog.objects.select_related(
            'from_account',
            'to_account',
            'user',
        )
        if for_update:
            queryset = queryset.select_for_update()
        return queryset.get(pk=log_id, user=user)

    def get_by_user(self, user: User) -> QuerySet[TransferMoneyLog]:
        """Get all transfer logs for a user.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[TransferMoneyLog]: QuerySet of user's transfer logs.
        """
        return TransferMoneyLog.objects.filter(user=user)

    def get_by_user_with_related(
        self,
        user: User,
    ) -> QuerySet[TransferMoneyLog]:
        """Get all transfer logs for a user with related objects optimized.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[TransferMoneyLog]: QuerySet with select_related
                optimizations.
        """
        return TransferMoneyLog.objects.filter(user=user).select_related(
            'to_account',
            'from_account',
            'user',
        )

    def get_by_user_ordered(
        self,
        user: User,
        limit: int | None = None,
    ) -> QuerySet[TransferMoneyLog]:
        """Get transfer logs for a user ordered by date.

        Args:
            user: User instance to filter by.
            limit: Optional limit on number of results.

        Returns:
            QuerySet[TransferMoneyLog]: QuerySet ordered by exchange_date
                descending.
        """
        queryset = (
            TransferMoneyLog.objects.filter(user=user)
            .select_related('to_account', 'from_account', 'user')
            .order_by('-exchange_date')
        )
        if limit:
            return queryset[:limit]
        return queryset

    def get_by_date_range(
        self,
        user: User,
        start: date,
        end: date,
    ) -> QuerySet[TransferMoneyLog]:
        """Get transfer logs for a user within a date range.

        Args:
            user: User instance to filter by.
            start: Start of date range (inclusive).
            end: End of date range (inclusive).

        Returns:
            QuerySet[TransferMoneyLog]: Filtered QuerySet.
        """
        return TransferMoneyLog.objects.by_user(user).by_date_range(start, end)

    def create_log(self, **kwargs: object) -> TransferMoneyLog:
        """Create a new transfer log.

        Args:
            **kwargs: Transfer log field values (user, from_account, to_account,
                amount, exchange_date, notes).

        Returns:
            TransferMoneyLog: Created transfer log instance.
        """
        return TransferMoneyLog.objects.create(**kwargs)

    def delete_log(
        self,
        transfer_log: TransferMoneyLog,
    ) -> tuple[int, dict[str, int]]:
        """Delete a transfer log instance."""
        return transfer_log.delete()

    def filter(self, **kwargs: object) -> QuerySet[TransferMoneyLog]:
        """Filter transfer logs by given criteria.

        Args:
            **kwargs: Filter criteria (field=value pairs).

        Returns:
            QuerySet[TransferMoneyLog]: Filtered QuerySet.
        """
        return TransferMoneyLog.objects.filter(**kwargs)
