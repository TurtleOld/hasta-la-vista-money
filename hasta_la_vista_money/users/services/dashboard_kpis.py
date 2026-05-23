"""KPI calculations for the dashboard header."""

from calendar import monthrange
from collections.abc import Iterable
from datetime import date, datetime, time
from decimal import Decimal
from typing import TypedDict

from django.db.models import Sum
from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.transactions.models import (
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User


class DashboardKpiDict(TypedDict):
    """Monthly KPI values shown above dashboard widgets."""

    period_start: date
    period_end: date
    income: Decimal
    expenses: Decimal
    net_result: Decimal
    savings_rate: Decimal
    top_expense_category_id: int | None
    top_expense_category_name: str | None
    top_expense_category_total: Decimal


def _current_month_bounds() -> tuple[date, date]:
    today = timezone.localdate()
    last_day = monthrange(today.year, today.month)[1]
    return today.replace(day=1), today.replace(day=last_day)


def _aware_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    return (
        timezone.make_aware(datetime.combine(start, time.min)),
        timezone.make_aware(datetime.combine(end, time.max)),
    )


def _sum_for_month(
    type_value: str,
    users: Iterable[User],
    start: datetime,
    end: datetime,
) -> Decimal:
    total = Transaction.objects.filter(
        user__in=users,
        type=type_value,
        date__gte=start,
        date__lte=end,
    ).aggregate(total=Sum('amount'))['total']
    return Decimal(total or constants.ZERO)


def get_dashboard_month_kpis(
    user: User,
    users: Iterable[User] | None = None,
) -> DashboardKpiDict:
    """Return current-month KPI values for the dashboard strip."""
    period_start, period_end = _current_month_bounds()
    start_dt, end_dt = _aware_bounds(period_start, period_end)
    selected_users = list(users or [user])

    income = _sum_for_month(
        TransactionType.INCOME,
        selected_users,
        start_dt,
        end_dt,
    )
    expenses = _sum_for_month(
        TransactionType.EXPENSE,
        selected_users,
        start_dt,
        end_dt,
    )
    net_result = income - expenses
    savings_rate = (
        net_result / income * constants.PERCENTAGE_MULTIPLIER
        if income > constants.ZERO
        else Decimal(constants.ZERO)
    )

    top_category = (
        Transaction.objects.filter(
            user__in=selected_users,
            type=TransactionType.EXPENSE,
            date__gte=start_dt,
            date__lte=end_dt,
        )
        .values('category__id', 'category__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')
        .first()
    )

    return {
        'period_start': period_start,
        'period_end': period_end,
        'income': income,
        'expenses': expenses,
        'net_result': net_result,
        'savings_rate': savings_rate,
        'top_expense_category_id': (
            int(top_category['category__id']) if top_category else None
        ),
        'top_expense_category_name': (
            str(top_category['category__name']) if top_category else None
        ),
        'top_expense_category_total': Decimal(
            top_category['total'] if top_category else constants.ZERO,
        ),
    }
