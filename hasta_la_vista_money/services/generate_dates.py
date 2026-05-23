"""Date list generation service.

This module provides services for generating date lists and planning
records for users.
"""

from collections.abc import Sequence
from datetime import date, datetime

from dateutil.relativedelta import relativedelta
from django.db.models import QuerySet

from hasta_la_vista_money import constants
from hasta_la_vista_money.budget.models import DateList, Planning
from hasta_la_vista_money.transactions.models import Category
from hasta_la_vista_money.users.models import User


class DateListGenerator:
    """Generate missing months and planning records for user.

    Creates DateList entries for next 12 months and optionally
    creates Planning records for expense or income categories.
    """

    def __init__(self, user: User, type_: str | None) -> None:
        """Initialize DateListGenerator.

        Args:
            user: User to generate dates for.
            type_: Planning type ('expense', 'income', or None).
        """
        self.user = user
        self.type_ = type_

    def run(self, current_date: datetime | QuerySet[DateList]) -> None:
        """Add 12 following months and optionally Planning records.

        Args:
            current_date: Starting date or QuerySet of DateList.
        """
        actual = self._actual_date(current_date)
        start = self._start_date(actual)
        months = self._month_sequence(
            start,
            constants.NUMBER_TWELFTH_MONTH_YEAR,
        )
        self._ensure_dates(months)
        self._ensure_planning(months)

    def _actual_date(
        self,
        current_date: datetime | QuerySet[DateList] | date,
    ) -> date:
        """Extract reference date from datetime or QuerySet.

        Args:
            current_date: Datetime, date, or QuerySet of DateList.

        Returns:
            Reference date.

        Raises:
            ValueError: If QuerySet is empty.
        """
        if isinstance(current_date, QuerySet):
            last = current_date.last()
            if last is None:
                error_msg = 'current_date must be datetime or QuerySet'
                raise ValueError(error_msg)
            return last.date
        if isinstance(current_date, datetime):
            return current_date.date()
        return current_date

    def _start_date(self, actual: date) -> date:
        """Get start date for generation.

        Returns month after last date in DateList, or actual if no
        dates exist.

        Args:
            actual: Fallback date if no DateList entries exist.

        Returns:
            Start date for month sequence.
        """
        last_obj = (
            DateList.objects.filter(user=self.user).order_by('-date').first()
        )
        return last_obj.date + relativedelta(months=1) if last_obj else actual

    def _month_sequence(self, start: date, count: int) -> list[date]:
        """Generate sequence of months from start.

        Args:
            start: Starting month date.
            count: Number of months to generate.

        Returns:
            List of month dates starting from start.
        """
        return [start + relativedelta(months=i) for i in range(count)]

    def _ensure_dates(self, months: Sequence[date]) -> None:
        """Create DateList entries for missing dates.

        Args:
            months: Sequence of month dates to ensure.
        """
        existing = set(
            DateList.objects.filter(
                user=self.user,
                date__in=months,
            ).values_list('date', flat=True),
        )
        to_create = [
            DateList(user=self.user, date=d)
            for d in months
            if d not in existing
        ]
        if to_create:
            DateList.objects.bulk_create(to_create)

    def _ensure_planning(self, months: Sequence[date]) -> None:
        """Create missing Planning records for specified type.

        Creates Planning entries for expense or income categories
        for given months if type_ is set.

        Args:
            months: Sequence of month dates to create planning for.
        """
        if self.type_ not in {'expense', 'income'}:
            return

        categories = list(
            Category.objects.filter(user=self.user, type=self.type_),
        )
        existing = set(
            Planning.objects.filter(
                user=self.user,
                planning_type=self.type_,
                date__in=months,
                category__in=categories,
            ).values_list('category_id', 'date'),
        )
        to_create = [
            Planning(
                user=self.user,
                category=c,
                date=d,
                planning_type=self.type_,
                amount=0,
            )
            for c in categories
            for d in months
            if (c.pk, d) not in existing
        ]

        if to_create:
            Planning.objects.bulk_create(to_create)


def generate_date_list(
    current_date: datetime | QuerySet[DateList],
    user: User,
    type_: str | None = None,
) -> None:
    """Generate date list and optionally planning records.

    Adds months and optionally Planning records without duplicates.

    Args:
        current_date: Starting date or QuerySet of DateList.
        user: User to generate dates for.
        type_: Planning type ('expense', 'income', or None).
    """
    DateListGenerator(user=user, type_=type_).run(current_date)
