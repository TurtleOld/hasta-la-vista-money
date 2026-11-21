"""Django repository for user statistics."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from django.db.models import Count, QuerySet, Sum

from hasta_la_vista_money.core.calendar_days import (
    calendar_day,
    filter_calendar_from,
    filter_calendar_to,
)
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.transactions.models import (
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.transactions.managers import TransactionQuerySet

_transaction_manager = cast('TransactionQuerySet', Transaction.objects)


class StatisticsRepository:
    """Repository for user statistics operations."""

    def get_accounts_aggregate(
        self,
        user: User,
        currency: str,
    ) -> dict[str, Decimal | int]:
        accounts_qs = Account.objects.filter(user=user, currency=currency)
        accounts_data = accounts_qs.aggregate(
            total_balance=Sum('balance'),
            accounts_count=Count('id'),
        )
        return {
            'total_balance': accounts_data['total_balance'] or Decimal(0),
            'accounts_count': accounts_data['accounts_count'] or 0,
        }

    def get_expenses_sum_by_period(
        self,
        user: User,
        currency: str,
        start_date: datetime,
        end_date: datetime | None = None,
    ) -> Decimal:
        qs = filter_calendar_from(
            _transaction_manager.without_adjustments().filter(
                user=user,
                account__currency=currency,
                type=TransactionType.EXPENSE,
            ),
            start_date,
        )
        if end_date:
            qs = filter_calendar_to(qs, end_date)
        result = qs.aggregate(total=Sum('amount'))['total']
        return result or Decimal(0)

    def get_income_sum_by_period(
        self,
        user: User,
        currency: str,
        start_date: datetime,
        end_date: datetime | None = None,
    ) -> Decimal:
        qs = filter_calendar_from(
            _transaction_manager.without_adjustments().filter(
                user=user,
                account__currency=currency,
                type=TransactionType.INCOME,
            ),
            start_date,
        )
        if end_date:
            qs = filter_calendar_to(qs, end_date)
        result = qs.aggregate(total=Sum('amount'))['total']
        return result or Decimal(0)

    def get_recent_expenses(
        self,
        user: User,
        limit: int = 5,
    ) -> QuerySet[Transaction]:
        return (
            Transaction.objects.filter(user=user, type=TransactionType.EXPENSE)
            .select_related('category', 'account')
            .annotate(_calendar_day=calendar_day())
            .order_by('-_calendar_day', '-date')[:limit]
        )

    def get_recent_incomes(
        self,
        user: User,
        limit: int = 5,
    ) -> QuerySet[Transaction]:
        return (
            Transaction.objects.filter(user=user, type=TransactionType.INCOME)
            .select_related('category', 'account')
            .annotate(_calendar_day=calendar_day())
            .order_by('-_calendar_day', '-date')[:limit]
        )

    def get_receipts_count(self, user: User) -> int:
        return Receipt.objects.filter(user=user).count()

    def get_top_expense_categories(
        self,
        user: User,
        currency: str,
        start_date: datetime,
        limit: int = 5,
    ) -> QuerySet[Transaction, dict[str, str | Decimal]]:
        return (
            filter_calendar_from(
                _transaction_manager.without_adjustments().filter(
                    user=user,
                    account__currency=currency,
                    type=TransactionType.EXPENSE,
                ),
                start_date,
            )
            .values('category__name')
            .annotate(total=Sum('amount'))
            .order_by('-total')[:limit]
        )
