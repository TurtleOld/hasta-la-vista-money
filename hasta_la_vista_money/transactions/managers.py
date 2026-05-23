"""Custom QuerySet for the Transaction model with type-aware shortcuts."""

from datetime import datetime, time
from typing import TYPE_CHECKING, Any

from django.db import models
from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

if TYPE_CHECKING:
    from datetime import date

    from hasta_la_vista_money.transactions.models import (  # noqa: F401
        Category,
        Transaction,
    )
    from hasta_la_vista_money.users.models import User


class TransactionQuerySet(models.QuerySet['Transaction']):
    """QuerySet for the unified Transaction model.

    Provides type-aware shortcuts (``incomes`` / ``expenses``) plus the
    filtering and aggregation helpers historically exposed by the income
    and expense apps.
    """

    def incomes(self) -> 'TransactionQuerySet':
        """Return only income transactions."""
        return self.filter(type='income')

    def expenses(self) -> 'TransactionQuerySet':
        """Return only expense transactions."""
        return self.filter(type='expense')

    def for_user(self, user: 'User') -> 'TransactionQuerySet':
        """Return transactions for a specific user."""
        return self.filter(user=user)

    def for_period(
        self,
        start_date: 'date',
        end_date: 'date',
    ) -> 'TransactionQuerySet':
        """Return transactions within an inclusive date range."""
        start_datetime = timezone.make_aware(
            datetime.combine(start_date, time.min),
        )
        end_datetime = timezone.make_aware(
            datetime.combine(end_date, time.max),
        )
        return self.filter(date__gte=start_datetime, date__lte=end_datetime)

    def for_category(self, category: 'Category') -> 'TransactionQuerySet':
        """Return transactions for the category or its direct descendants."""
        return self.filter(
            Q(category=category) | Q(category__parent_category=category),
        )

    def total_amount(self) -> int | float:
        """Return the sum of ``amount`` for the queryset."""
        return self.aggregate(total=Sum('amount'))['total'] or 0

    def by_month(self) -> Any:
        """Return transactions grouped by month with running totals."""
        return (
            self.annotate(month=TruncMonth('date'))
            .values('month')
            .annotate(total=Sum('amount'))
            .order_by('month')
        )
