from collections.abc import Iterable
from datetime import date, datetime, time
from decimal import Decimal
from statistics import pstdev
from typing import Any

from dateutil.relativedelta import relativedelta
from django.db.models import Sum
from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.loan.models import PaymentSchedule
from hasta_la_vista_money.transactions.models import (
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User


def _aware_day(day: date, *, end_of_day: bool = False) -> datetime:
    time_value = time.max if end_of_day else time.min
    return timezone.make_aware(datetime.combine(day, time_value))


def _monthly_net_flows(
    users: Iterable[User],
    start: date,
    end: date,
) -> list[Decimal]:
    rows = (
        Transaction.objects.filter(
            user__in=users,
            date__gte=_aware_day(start),
            date__lte=_aware_day(end, end_of_day=True),
        )
        .values('type', 'date__year', 'date__month')
        .annotate(total=Sum('amount'))
    )
    monthly: dict[tuple[int, int], Decimal] = {}
    for row in rows:
        key = (row['date__year'], row['date__month'])
        amount = Decimal(row['total'] or 0)
        if row['type'] == TransactionType.INCOME:
            monthly[key] = monthly.get(key, Decimal(0)) + amount
        else:
            monthly[key] = monthly.get(key, Decimal(0)) - amount

    result: list[Decimal] = []
    current = start.replace(day=1)
    last = end.replace(day=1)
    while current <= last:
        result.append(monthly.get((current.year, current.month), Decimal(0)))
        current += relativedelta(months=constants.ONE)
    return result


def build_cashflow_forecast(
    *,
    users: Iterable[User],
    accounts: Iterable[Account],
    today: date,
    months: int = 6,
) -> dict[str, list[float | str | None]]:
    """Return 3/6 month cash-flow forecast from the latest 6 months."""
    history_start = today.replace(day=1) - relativedelta(months=5)
    flows = _monthly_net_flows(users, history_start, today)
    if not flows:
        return {
            'forecast_labels': [],
            'forecast_balance': [],
            'forecast_lower': [],
            'forecast_upper': [],
        }

    balances = [Decimal(account.balance or 0) for account in accounts]
    current_balance = sum(balances, Decimal(0))
    average_flow = sum(flows, Decimal(0)) / Decimal(len(flows))
    deviation = (
        Decimal(str(pstdev([float(flow) for flow in flows])))
        if len(flows) > 1
        else Decimal(0)
    )

    labels: list[str] = []
    forecast: list[float] = []
    lower: list[float] = []
    upper: list[float] = []
    for index in range(1, months + 1):
        projected_month = today.replace(day=1) + relativedelta(months=index)
        projected = current_balance + (average_flow * Decimal(index))
        corridor = deviation * Decimal(index).sqrt()
        labels.append(projected_month.isoformat())
        forecast.append(float(projected))
        lower.append(float(projected - corridor))
        upper.append(float(projected + corridor))

    return {
        'forecast_labels': labels,
        'forecast_balance': forecast,
        'forecast_lower': lower,
        'forecast_upper': upper,
    }


def build_payment_calendar(
    *,
    users: Iterable[User],
    credit_cards: list[dict[str, Any]],
    today: date,
    months: int = 6,
) -> list[dict[str, Any]]:
    """Return upcoming credit card grace dates and loan payments."""
    end = today + relativedelta(months=months)
    events: list[dict[str, Any]] = []

    for card in credit_cards:
        for payment in card.get('payment_schedule', []):
            if payment.get('remaining_debt', constants.ZERO) <= constants.ZERO:
                continue
            try:
                day, month, year = str(payment['payment_due']).split('.')
                due = date(int(year), int(month), int(day))
            except ValueError:
                continue
            if today <= due <= end:
                events.append(
                    {
                        'date': due,
                        'type': 'credit_card',
                        'title': f'{card["name"]}: конец грейса',
                        'amount': payment['remaining_debt'],
                        'currency': card.get('currency', ''),
                        'is_overdue': payment.get('is_overdue', False),
                    },
                )

    schedules = (
        PaymentSchedule.objects.filter(
            user__in=users,
            date__date__gte=today,
            date__date__lte=end,
        )
        .select_related('loan', 'loan__account')
        .order_by('date')
    )
    events.extend(
        [
            {
                'date': schedule.date.date(),
                'type': 'loan',
                'title': f'Кредит #{schedule.loan_id}',
                'amount': float(schedule.monthly_payment),
                'currency': schedule.loan.account.currency,
                'is_overdue': False,
            }
            for schedule in schedules
        ],
    )

    return sorted(events, key=lambda event: event['date'])
