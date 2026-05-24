"""Django repository for the unified Transaction model.

Provides the data-access layer used by services and views. Methods that
accept a ``type`` parameter return a queryset filtered to incomes or
expenses; without it the queryset spans both.
"""

from datetime import date, datetime, time
from typing import Any

from django.db.models import QuerySet, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import Category, Transaction
from hasta_la_vista_money.users.models import User


class TransactionRepository:
    """Repository for Transaction model operations."""

    def get_by_id(self, transaction_id: int) -> Transaction:
        """Return the transaction with the given primary key."""
        return Transaction.objects.get(pk=transaction_id)

    def get_by_user(
        self,
        user: User,
        type_value: str | None = None,
    ) -> QuerySet[Transaction]:
        """Return transactions for a user with related objects preloaded."""
        qs = Transaction.objects.for_user(user).select_related(
            'user',
            'category',
            'account',
        )
        if type_value is not None:
            qs = qs.filter(type=type_value)
        return qs

    def get_by_user_and_group(
        self,
        user: User,
        group_id: str | None = None,
        type_value: str | None = None,
    ) -> QuerySet[Transaction]:
        """Return transactions filtered by user or group membership."""
        if not group_id or group_id == 'my':
            return self.get_by_user(user, type_value=type_value)

        user_with_groups = User.objects.prefetch_related('groups').get(
            pk=user.pk,
        )
        if user_with_groups.groups.filter(id=group_id).exists():
            group_users = list(User.objects.filter(groups__id=group_id))
            qs = Transaction.objects.filter(
                user__in=group_users,
            ).select_related('user', 'category', 'account')
            if type_value is not None:
                qs = qs.filter(type=type_value)
            return qs

        return Transaction.objects.none()

    def get_by_period(
        self,
        user: User,
        start_date: date,
        end_date: date,
        type_value: str | None = None,
    ) -> QuerySet[Transaction]:
        """Return transactions for a user within a date period."""
        qs = Transaction.objects.for_user(user).for_period(
            start_date,
            end_date,
        )
        if type_value is not None:
            qs = qs.filter(type=type_value)
        return qs

    def filter_by_user_and_date_range(
        self,
        user: User,
        start_date: datetime,
        end_date: datetime,
        type_value: str | None = None,
    ) -> QuerySet[Transaction]:
        """Filter transactions by user and a datetime range."""
        qs = Transaction.objects.filter(
            user=user,
            date__gte=start_date,
            date__lte=end_date,
        )
        if type_value is not None:
            qs = qs.filter(type=type_value)
        return qs

    def get_by_category(
        self,
        user: User,
        category: Category,
    ) -> QuerySet[Transaction]:
        """Return transactions for the given category or its descendants."""
        return Transaction.objects.for_user(user).for_category(category)

    def get_by_account(
        self,
        user: User,
        account_id: int,
        type_value: str | None = None,
    ) -> QuerySet[Transaction]:
        """Return transactions for a user filtered by account id."""
        qs = Transaction.objects.for_user(user).filter(account_id=account_id)
        if type_value is not None:
            qs = qs.filter(type=type_value)
        return qs

    def filter_by_account(
        self,
        account: Account,
        type_value: str | None = None,
    ) -> QuerySet[Transaction]:
        """Return transactions for the account ordered by date."""
        qs = Transaction.objects.filter(account=account).order_by('date')
        if type_value is not None:
            qs = qs.filter(type=type_value)
        return qs

    def create_transaction(self, **kwargs: object) -> Transaction:
        """Create a transaction, normalising the ``date`` value."""
        if 'date' in kwargs:
            date_value = kwargs['date']
            if isinstance(date_value, date) and not isinstance(
                date_value,
                datetime,
            ):
                kwargs['date'] = timezone.make_aware(
                    datetime.combine(date_value, time.min),
                )
            elif isinstance(date_value, datetime) and timezone.is_naive(
                date_value,
            ):
                kwargs['date'] = timezone.make_aware(date_value)
        return Transaction.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[Transaction]:
        """Filter transactions by arbitrary criteria."""
        return Transaction.objects.filter(**kwargs)

    def filter_with_select_related(
        self,
        *related_fields: str,
        **kwargs: object,
    ) -> QuerySet[Transaction]:
        """Filter with ``select_related`` for the given fields."""
        return Transaction.objects.filter(**kwargs).select_related(
            *related_fields,
        )

    def get_aggregated_by_date(
        self,
        user: User,
        type_value: str | None = None,
    ) -> QuerySet[Transaction, dict[str, Any]]:
        """Return transactions aggregated by date for charts."""
        qs = Transaction.objects.filter(user=user)
        if type_value is not None:
            qs = qs.filter(type=type_value)
        return (
            qs.values('date')
            .annotate(total_amount=Sum('amount'))
            .order_by('date')
        )

    def get_top_categories(
        self,
        user: User,
        year_start: datetime,
        type_value: str | None = None,
        limit: int = 10,
    ) -> QuerySet[Transaction, dict[str, Any]]:
        """Return the top-N categories by total amount."""
        qs = Transaction.objects.filter(user=user, date__gte=year_start)
        if type_value is not None:
            qs = qs.filter(type=type_value)
        return (
            qs.values('category__id', 'category__name')
            .annotate(total=Sum('amount'))
            .order_by('-total')[:limit]
        )

    def filter_by_user_category_and_month(
        self,
        user: User,
        category: Category,
        month: date,
    ) -> QuerySet[Transaction]:
        """Return transactions for a user/category in a specific month."""
        return Transaction.objects.filter(
            user=user,
            category=category,
            date__year=month.year,
            date__month=month.month,
        ).select_related('user', 'category')

    def aggregate_by_month(
        self,
        user: User,
        account: Account | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        type_value: str | None = None,
    ) -> QuerySet[Transaction, dict[str, Any]]:
        """Aggregate transactions by month (used by balance-trend service)."""
        qs = Transaction.objects.filter(user=user)
        if account is not None:
            qs = qs.filter(account=account)
        if start_date is not None:
            qs = qs.filter(date__gte=start_date)
        if end_date is not None:
            qs = qs.filter(date__lte=end_date)
        if type_value is not None:
            qs = qs.filter(type=type_value)
        return (
            qs.annotate(month=TruncMonth('date'))
            .values('month')
            .annotate(total=Sum('amount'))
        )
