import json
from calendar import monthrange
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from dateutil.relativedelta import relativedelta
from django.core.cache import cache
from django.core.paginator import Page, Paginator
from django.db.models import QuerySet, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from typing_extensions import TypedDict

from core.protocols.services import AccountServiceProtocol

if TYPE_CHECKING:
    from config.containers import ApplicationContainer

from hasta_la_vista_money import constants
from hasta_la_vista_money.constants import (
    ACCOUNT_TYPE_CREDIT,
    ACCOUNT_TYPE_CREDIT_CARD,
    RECEIPT_OPERATION_PURCHASE,
    RECEIPT_OPERATION_RETURN,
)
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.finance_account.prepare import (
    collect_info_expense,
    collect_info_income,
    sort_expense_income,
)
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.services.views import collect_info_receipt
from hasta_la_vista_money.transactions.models import (
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.users.services.cache import (
    get_user_detailed_statistics_cache_key,
)
from hasta_la_vista_money.users.services.category_statistics_service import (
    _category_choices,
    _category_ids,
    _filter_transaction_queryset,
    _filtered_accounts,
    _filtered_receipts,
    _filtered_transactions,
    _match_income_expense_search,
    _receipt_details,
    _top_categories_with_comparison,
    _transfer_logs,
)
from hasta_la_vista_money.users.services.forecast import (
    build_cashflow_forecast,
    build_payment_calendar,
)
from hasta_la_vista_money.users.services.monthly_statistics_service import (
    BudgetDataDict,
    MonthDataDict,
    StatisticsChoiceDict,
    StatisticsFilters,
    _budgets_data,
    _date_to_aware,
    _member_choices,
    _month_ranges_for_filter,
    _period_choices,
    _resolve_statistics_members,
    _six_months_data,
    _sum_amount_for_period,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.services import (
        GracePeriodInfoDict,
    )


# ---------------------------------------------------------------------------
# TypedDicts (credit-card and output types)
# ---------------------------------------------------------------------------


class ChartDataDict(TypedDict):
    """Chart data.

    Attributes:
        labels: List of chart labels.
        expense_data: List of expense values.
        income_data: List of income values.
    """

    labels: list[str]
    expense_data: list[float | None]
    income_data: list[float | None]
    forecast_balance: list[float | None]
    forecast_lower: list[float | None]
    forecast_upper: list[float | None]


class DeltaByCurrencyDict(TypedDict, total=False):
    """Balance change by currency.

    Attributes:
        delta: Balance change amount.
        percent: Balance change percentage.
    """

    delta: float
    percent: float | None


class CardMonthDict(TypedDict):
    """Credit card month data."""

    month: str
    purchase_start: datetime
    purchase_end: datetime
    grace_end: datetime
    debt_for_month: float
    is_overdue: bool
    days_until_due: int
    payments_made: float
    remaining_debt: float
    is_paid: bool


class CardHistoryDict(TypedDict):
    """Credit card history by month."""

    month: str
    debt: float
    final_debt: float
    grace_end: str
    is_overdue: bool


class PaymentItemDict(TypedDict):
    """Payment item."""

    amount: Decimal
    date: date | datetime


class PaymentScheduleItemDict(TypedDict):
    """Payment schedule item."""

    month: str
    sum_expense: float
    payments_made: float
    remaining_debt: float
    payment_due: str
    is_overdue: bool
    days_until_due: int
    is_paid: bool


class CreditCardDataDict(TypedDict, total=False):
    """Credit card data."""

    name: str
    limit: Decimal | None
    debt_now: Decimal | None
    current_grace_info: 'GracePeriodInfoDict'
    history: list[CardHistoryDict]
    currency: str
    card_obj: Account
    limit_left: Decimal
    payment_schedule: list[PaymentScheduleItemDict]
    utilization_chart: dict[str, list[float] | list[str]]
    utilization_chart_id: str
    minimum_payment_forecast: list[dict[str, float | int]]


class CreditCardSummaryDict(TypedDict):
    """Credit card risk summary."""

    overdue_count: int
    expiring_count: int
    at_risk_count: int
    total_remaining_debt: Decimal


class IncomeExpenseDict(TypedDict):
    """Income/expense data."""

    id: int
    date: date
    account__name_account: str
    category__name: str
    user__username: str
    amount: Decimal
    type: str


class UserDetailedStatisticsDict(TypedDict):
    """User detailed statistics."""

    months_data: list[MonthDataDict]
    budgets_data: list[BudgetDataDict]
    top_expense_categories: list[dict[str, Any]]
    top_income_categories: list[dict[str, Any]]
    receipt_info_by_month: QuerySet[Receipt]
    income_expense: list[IncomeExpenseDict]
    transfer_money_log: QuerySet[TransferMoneyLog]
    accounts: QuerySet[Account]
    balances_by_currency: dict[str, float]
    delta_by_currency: dict[str, DeltaByCurrencyDict]
    chart_combined: ChartDataDict
    user: User
    credit_cards_data: list[CreditCardDataDict]
    statistics_filter: StatisticsFilters
    statistics_period_choices: list[StatisticsChoiceDict]
    statistics_account_choices: QuerySet[Account]
    statistics_currency_choices: list[str]
    statistics_category_choices: list[StatisticsChoiceDict]
    statistics_member_choices: list[StatisticsChoiceDict]
    statistics_members: list[User]
    statistics_alerts: list[dict[str, Any]]
    top_receipt_products: list[dict[str, Any]]
    top_receipt_sellers: list[dict[str, Any]]
    average_receipts_by_month: list[dict[str, Any]]
    receipt_page: Page[Receipt]
    income_expense_page: Page[Any]
    transfer_money_log_page: Page[TransferMoneyLog]
    credit_cards_summary: CreditCardSummaryDict
    payment_calendar: list[dict[str, Any]]
    chart_combined_json: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _paginate(queryset: Any, page_number: int) -> Page[Any]:
    return Paginator(queryset, constants.PAGINATE_BY_DEFAULT).get_page(
        page_number,
    )


def _dates_amounts(
    dataset: Iterable[dict[str, Any]],
) -> tuple[list[str], list[float]]:
    dates, amounts = [], []
    for item in dataset:
        dates.append(item['date'].strftime('%Y-%m-%d'))
        amounts.append(float(item['total_amount']))
    return dates, amounts


def _build_chart(
    users: Iterable[User],
    stats_filter: StatisticsFilters,
    start: date,
    end: date,
    forecast: dict[str, list[float | str | None]] | None = None,
) -> ChartDataDict:
    exp_ds = (
        _filtered_transactions(
            TransactionType.EXPENSE,
            users,
            stats_filter,
            start=start,
            end=end,
        )
        .values('date')
        .annotate(total_amount=Sum('amount'))
        .order_by('date')
    )
    inc_ds = (
        _filtered_transactions(
            TransactionType.INCOME,
            users,
            stats_filter,
            start=start,
            end=end,
        )
        .values('date')
        .annotate(total_amount=Sum('amount'))
        .order_by('date')
    )

    exp_dates, exp_amts = _dates_amounts(exp_ds)
    inc_dates, inc_amts = _dates_amounts(inc_ds)
    exp_map = dict(zip(exp_dates, exp_amts, strict=False))
    inc_map = dict(zip(inc_dates, inc_amts, strict=False))

    all_dates = sorted(set(exp_dates + inc_dates))
    if not all_dates:
        all_dates = []

    exp_series: list[float | None] = [
        exp_map.get(d, constants.ZERO) for d in all_dates
    ]
    inc_series: list[float | None] = [
        inc_map.get(d, constants.ZERO) for d in all_dates
    ]

    if len(all_dates) == constants.ONE:
        d = date.fromisoformat(all_dates[0])
        dt = datetime.combine(d, time.min)
        aware = timezone.make_aware(dt)
        prev = (aware - timedelta(days=constants.ONE)).date().isoformat()

        all_dates = [prev, *all_dates]
        exp_series = [constants.ZERO, *exp_series]
        inc_series = [constants.ZERO, *inc_series]

    forecast_labels = [
        str(label)
        for label in (forecast or {}).get(
            'forecast_labels',
            [],
        )
    ]
    labels = [*all_dates, *forecast_labels]
    padding = [None] * len(all_dates)
    forecast_padding = [None] * len(forecast_labels)

    return {
        'labels': labels,
        'expense_data': [*exp_series, *forecast_padding],
        'income_data': [*inc_series, *forecast_padding],
        'forecast_balance': [
            *padding,
            *((forecast or {}).get('forecast_balance', [])),
        ],
        'forecast_lower': [
            *padding,
            *((forecast or {}).get('forecast_lower', [])),
        ],
        'forecast_upper': [
            *padding,
            *((forecast or {}).get('forecast_upper', [])),
        ],
    }


def _balances_and_delta(
    accounts: QuerySet[Account],
    today: date,
) -> tuple[dict[str, float], dict[str, DeltaByCurrencyDict]]:
    balances_now: dict[str, float] = defaultdict(float)
    for acc in accounts:
        balances_now[acc.currency] += float(acc.balance)

    prev_day = today - timedelta(days=1)
    balances_prev: dict[str, float] = defaultdict(float)
    for acc in accounts:
        if acc.created_at and acc.created_at.date() <= prev_day:
            balances_prev[acc.currency] += float(acc.balance)

    delta = {}
    for cur in balances_now:
        now_val = balances_now.get(cur, 0.0)
        prev_val = balances_prev.get(cur, 0.0)
        diff = now_val - prev_val
        pct = (
            (diff / prev_val * constants.PERCENTAGE_MULTIPLIER)
            if prev_val
            else None
        )
        delta[cur] = {'delta': diff, 'percent': pct}

    return dict(balances_now), delta  # type: ignore[return-value]


def _statistics_alerts(
    users: Iterable[User],
    stats_filter: StatisticsFilters,
    budgets: list[BudgetDataDict],
    credit_cards: list[CreditCardDataDict],
    today: date,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    alerts.extend(
        [
            {
                'type': 'danger' if budget['over_limit'] else 'warning',
                'title': 'Бюджет',
                'message': '{}: {:.1f}%'.format(
                    budget['category_name'],
                    budget['usage_percent'],
                ),
            }
            for budget in budgets
            if budget['over_limit'] or budget['near_limit']
        ],
    )

    for card in credit_cards:
        for payment in card.get('payment_schedule', []):
            if payment['remaining_debt'] <= 0:
                continue
            if payment['is_overdue']:
                alerts.append(
                    {
                        'type': 'danger',
                        'title': 'Кредитная карта',
                        'message': f'{card["name"]}: грейс просрочен',
                    },
                )
            elif (
                0
                < payment['days_until_due']
                <= constants.NUMBER_SEVENTH_MONTH_YEAR
            ):
                alerts.append(
                    {
                        'type': 'warning',
                        'title': 'Кредитная карта',
                        'message': '{}: до конца грейса {} дн.'.format(
                            card['name'],
                            payment['days_until_due'],
                        ),
                    },
                )

    month_start = today.replace(day=1)
    income = _sum_amount_for_period(
        TransactionType.INCOME,
        users,
        month_start,
        today,
        stats_filter,
    )
    expenses = _sum_amount_for_period(
        TransactionType.EXPENSE,
        users,
        month_start,
        today,
        stats_filter,
    )
    if expenses > income:
        alerts.append(
            {
                'type': 'danger',
                'title': 'Расходы выше доходов',
                'message': f'Превышение за месяц: {expenses - income:.2f} ₽',
            },
        )
    return alerts[: constants.TEN]


# ---------------------------------------------------------------------------
# Credit-card helpers
# ---------------------------------------------------------------------------


def _calculate_grace_period_end(
    card: Account,
    purchase_start_date: date,
    purchase_end: datetime,
    account_service: AccountServiceProtocol,
) -> datetime:
    """Calculate grace period end date.

    Args:
        card: Account (credit card) instance.
        purchase_start_date: Purchase period start date.
        purchase_end: Purchase period end datetime.
        account_service: Account service for payment schedule calculations.

    Returns:
        Grace period end datetime.
    """
    bank = getattr(card, 'bank', None)
    if bank == 'SBERBANK':
        grace_end_date = purchase_start_date + relativedelta(
            months=constants.GRACE_PERIOD_MONTHS_SBERBANK,
        )
        last_grace_day = monthrange(
            grace_end_date.year,
            grace_end_date.month,
        )[1]
        return timezone.make_aware(
            datetime.combine(
                grace_end_date.replace(day=last_grace_day),
                time.max,
            ),
        )
    if bank == 'RAIFFAISENBANK':
        schedule = account_service.calculate_raiffeisenbank_payment_schedule(
            card,
            purchase_start_date,
        )
        if schedule and 'grace_end_date' in schedule:
            return schedule['grace_end_date']
        return purchase_end
    return purchase_end


def _build_expenses_receipts_dicts(
    expenses_by_month: Any,
    receipts_by_month: Any,
) -> tuple[dict[date, Decimal], dict[date, dict[int, Decimal]]]:
    """Build expenses and receipts dictionaries by month."""
    expenses_dict: dict[date, Decimal] = {}
    for item in expenses_by_month:
        month_date = item['month'].date().replace(day=1)
        expenses_dict[month_date] = Decimal(str(item['total'] or 0))

    receipts_dict: dict[date, dict[int, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal(0)),
    )
    for item in receipts_by_month:
        month_date = item['month'].date().replace(day=1)
        operation_type = item['operation_type']
        receipts_dict[month_date][operation_type] = Decimal(
            str(item['total'] or 0),
        )
    return expenses_dict, receipts_dict


def _build_single_card_month(
    month_date: date,
    expenses_dict: dict[date, Decimal],
    receipts_dict: dict[date, dict[int, Decimal]],
    card: Account,
    account_service: AccountServiceProtocol,
    now: datetime,
) -> tuple[CardMonthDict, float]:
    """Build data for single card month.

    Args:
        month_date: Month date to build data for.
        expenses_dict: Dictionary mapping month date to expense amount.
        receipts_dict: Dictionary mapping month date to receipts by
            operation type.
        card: Account (credit card) instance.
        account_service: Account service for payment schedule calculations.
        now: Current datetime.

    Returns:
        Tuple of (month_data, final_debt) where month_data contains
        card statistics for the month and final_debt is the calculated debt.
    """
    purchase_start_date = month_date.replace(day=1)
    last_day = monthrange(
        purchase_start_date.year,
        purchase_start_date.month,
    )[1]
    purchase_start = timezone.make_aware(
        datetime.combine(purchase_start_date, time.min),
    )
    purchase_end = timezone.make_aware(
        datetime.combine(
            purchase_start_date.replace(day=last_day),
            time.max,
        ),
    )

    exp_sum = expenses_dict.get(purchase_start_date, Decimal(0))
    rcpt_expense = receipts_dict[purchase_start_date].get(
        RECEIPT_OPERATION_PURCHASE,
        Decimal(0),
    )
    rcpt_return = receipts_dict[purchase_start_date].get(
        RECEIPT_OPERATION_RETURN,
        Decimal(0),
    )

    debt = float(exp_sum) + float(rcpt_expense) - float(rcpt_return)
    grace_end = _calculate_grace_period_end(
        card,
        purchase_start_date,
        purchase_end,
        account_service,
    )

    days_left = (
        (grace_end.date() - now.date()).days
        if now <= grace_end
        else constants.ZERO
    )
    overdue = now > grace_end and debt > constants.ZERO

    month_data: CardMonthDict = {
        'month': purchase_start_date.strftime('%m.%Y'),
        'purchase_start': purchase_start,
        'purchase_end': purchase_end,
        'grace_end': grace_end,
        'debt_for_month': debt,
        'is_overdue': overdue,
        'days_until_due': days_left,
        'payments_made': 0.0,
        'remaining_debt': 0.0,
        'is_paid': False,
    }

    final_debt = debt
    if (
        getattr(card, 'bank', None) == 'RAIFFAISENBANK'
        and debt > constants.ZERO
    ):
        schedule = account_service.calculate_raiffeisenbank_payment_schedule(
            card,
            purchase_start,
        )
        if schedule and 'final_debt' in schedule:
            final_debt = float(schedule['final_debt'])

    return month_data, final_debt


def _card_months_block(
    card: Account,
    today: date,
    stats_filter: StatisticsFilters,
    account_service: AccountServiceProtocol,
) -> tuple[list[CardMonthDict], list[CardHistoryDict]]:
    """Build months data block for card."""
    now = timezone.now()
    month_ranges = _month_ranges_for_filter(today, stats_filter)
    if not month_ranges:
        return [], []
    period_start = month_ranges[0][1]
    period_end = month_ranges[-1][2]

    expenses_by_month = (
        _filter_transaction_queryset(
            Transaction.objects.filter(
                user=card.user,
                account=card,
                type=TransactionType.EXPENSE,
            ),
            stats_filter=stats_filter,
            type_value=TransactionType.EXPENSE,
            start=period_start,
            end=period_end,
        )
        .annotate(month=TruncMonth('date'))
        .values('month')
        .annotate(total=Sum('amount'))
    )

    receipts_by_month = (
        _filtered_receipts(
            [card.user],
            stats_filter,
            period_start,
            period_end,
            account=card,
        )
        .annotate(month=TruncMonth('receipt_date'))
        .values('month', 'operation_type')
        .annotate(total=Sum('total_sum'))
    )

    expenses_dict, receipts_dict = _build_expenses_receipts_dicts(
        expenses_by_month,
        receipts_by_month,
    )

    months: list[CardMonthDict] = []
    history: list[CardHistoryDict] = []

    for month_date, _range_start, _range_end in month_ranges:
        month_data, final_debt = _build_single_card_month(
            month_date,
            expenses_dict,
            receipts_dict,
            card,
            account_service,
            now,
        )
        months.append(month_data)

        history.append(
            {
                'month': str(month_data['month']),
                'debt': month_data['debt_for_month'],
                'final_debt': final_debt,
                'grace_end': month_data['grace_end'].strftime('%d.%m.%Y'),
                'is_overdue': month_data['is_overdue'],
            },
        )

    return months, history


def _collect_card_payments(
    card: Account,
    period_start: date,
    period_end: date,
) -> list[PaymentItemDict]:
    """Collect all credit-card repayments in the period.

    Includes both TransferMoneyLog entries (canonical repayments) and
    income transactions, since users sometimes record repayments as
    income rather than inter-account transfers.
    """
    transfers = list(
        TransferMoneyLog.objects.filter(
            user=card.user,
            to_account=card,
            exchange_date__date__gte=period_start,
            exchange_date__date__lte=period_end,
        ).values('amount', 'exchange_date'),
    )
    income_txns = list(
        Transaction.objects.filter(
            user=card.user,
            account=card,
            type=TransactionType.INCOME,
            date__date__gte=period_start,
            date__date__lte=period_end,
        ).values('amount', 'date'),
    )
    return [
        {'amount': Decimal(str(p['amount'])), 'date': p['exchange_date']}
        for p in transfers
    ] + [
        {'amount': Decimal(str(p['amount'])), 'date': p['date']}
        for p in income_txns
    ]


def _pre_period_debt_for_card(
    card: Account,
    payments: list[PaymentItemDict],
    months: list[CardMonthDict],
) -> float:
    """Compute the credit-card debt that existed before the tracked period.

    Uses the current account balance as an anchor:
        debt_at_period_start =
            (limit - balance) + period_income - period_expenses

    Payments are applied to this old debt first; only the surplus is
    available to reduce current-period month balances.
    """
    limit = float(card.limit_credit or 0)
    if limit <= constants.ZERO:
        return constants.ZERO
    total_income = sum(float(p['amount']) for p in payments)
    total_expenses = sum(float(m['debt_for_month']) for m in months)
    return max(
        limit - float(card.balance) + total_income - total_expenses,
        constants.ZERO,
    )


def _apply_payments_to_months(
    months: list[CardMonthDict],
    payments: list[PaymentItemDict],
    pre_period_debt: float = 0.0,
) -> None:
    for m in months:
        debt = float(m['debt_for_month'])
        if debt <= constants.ZERO:
            m['payments_made'] = constants.ZERO
            m['remaining_debt'] = constants.ZERO
            m['is_paid'] = True
            continue
        paid_before_due = sum(
            float(p['amount']) for p in payments if p['date'] <= m['grace_end']
        )
        prior_debt = pre_period_debt + sum(
            float(prev['debt_for_month'])
            for prev in months
            if prev['grace_end'] < m['grace_end']
        )
        available_for_month = max(paid_before_due - prior_debt, constants.ZERO)
        paid = min(available_for_month, debt)
        m['payments_made'] = paid
        m['remaining_debt'] = max(debt - paid, constants.ZERO)
        m['is_paid'] = m['remaining_debt'] <= constants.ZERO


def _build_payment_schedule(
    months: list[CardMonthDict],
    history: list[CardHistoryDict],
    card: Account,
) -> list[PaymentScheduleItemDict]:
    schedule: list[PaymentScheduleItemDict] = []
    for m in months:
        if m['debt_for_month'] <= constants.ZERO:
            continue
        due = m['grace_end'].strftime('%d.%m.%Y')
        if getattr(card, 'bank', None) == 'RAIFFAISENBANK':
            for h in history:
                if h['month'] == m['month']:
                    due = h['grace_end']
                    break
        schedule.append(
            {
                'month': m['month'],
                'sum_expense': m['debt_for_month'],
                'payments_made': m['payments_made'],
                'remaining_debt': m['remaining_debt'],
                'payment_due': due,
                'is_overdue': m['is_overdue'],
                'days_until_due': m['days_until_due'],
                'is_paid': m['is_paid'],
            },
        )
    return schedule


def _credit_card_utilization_chart(
    history: list[CardHistoryDict],
    limit: Decimal | None,
) -> dict[str, list[float] | list[str]]:
    limit_value = float(limit or 0)
    labels: list[str] = []
    values: list[float] = []
    for item in history[-constants.MONTHS_IN_YEAR :]:
        labels.append(item['month'])
        if limit_value <= constants.ZERO:
            values.append(constants.ZERO)
            continue
        values.append(
            round(
                max(item['final_debt'], constants.ZERO)
                / limit_value
                * constants.PERCENTAGE_MULTIPLIER,
                2,
            ),
        )
    return {'labels': labels, 'values': values}


def _minimum_payment_forecast(
    debt: Decimal | None,
) -> list[dict[str, float | int]]:
    remaining = Decimal(str(max(debt or 0, constants.ZERO)))
    if remaining <= constants.ZERO:
        return []
    forecast: list[dict[str, float | int]] = []
    for month_number in range(constants.ONE, constants.MONTHS_IN_YEAR + 1):
        payment = remaining * Decimal(
            str(constants.SBERBANK_MIN_PAYMENT_PERCENTAGE),
        )
        remaining = max(remaining - payment, Decimal(str(constants.ZERO)))
        forecast.append(
            {
                'month': month_number,
                'minimum_payment': float(payment),
                'remaining_debt': float(remaining),
            },
        )
        if remaining <= constants.ZERO:
            break
    return forecast


def _credit_cards_summary(
    credit_cards: list[CreditCardDataDict],
) -> CreditCardSummaryDict:
    overdue_count = 0
    expiring_count = 0
    total_remaining_debt = Decimal(str(constants.ZERO))
    for card in credit_cards:
        for payment in card.get('payment_schedule', []):
            remaining_debt = Decimal(str(payment['remaining_debt']))
            if remaining_debt <= constants.ZERO:
                continue
            total_remaining_debt += remaining_debt
            if payment['is_overdue']:
                overdue_count += constants.ONE
            elif (
                constants.ZERO
                < payment['days_until_due']
                <= constants.NUMBER_SEVENTH_MONTH_YEAR
            ):
                expiring_count += constants.ONE
    return {
        'overdue_count': overdue_count,
        'expiring_count': expiring_count,
        'at_risk_count': overdue_count + expiring_count,
        'total_remaining_debt': total_remaining_debt,
    }


def _payment_schedule_remaining_debt(
    schedule: list[PaymentScheduleItemDict],
) -> Decimal:
    return sum(
        (Decimal(str(payment['remaining_debt'])) for payment in schedule),
        Decimal(str(constants.ZERO)),
    )


def compute_total_payment_schedule_debt(
    accounts: QuerySet[Account],
    account_service: AccountServiceProtocol,
) -> Decimal:
    """Sum ``remaining_debt`` from payment schedules across credit cards.

    Builds the same payment schedule used in the detailed-statistics
    table ("График платежей по беспроцентному периоду") for every
    credit account in the queryset, then sums the per-month
    ``remaining_debt`` values. The result matches the "Осталось"
    column on the statistics page.

    Args:
        accounts: QuerySet of accounts to inspect.
        account_service: Account service used for grace and debt
            calculations.

    Returns:
        Non-negative Decimal representing total outstanding debt
        across credit-card payment schedules.
    """
    today = timezone.now().date()
    stats_filter = StatisticsFilters()
    period_start, period_end = stats_filter.date_range(today)

    credit_cards = accounts.filter(
        type_account__in=[ACCOUNT_TYPE_CREDIT_CARD, ACCOUNT_TYPE_CREDIT],
    )

    total = Decimal(str(constants.ZERO))
    for card in credit_cards:
        months, history = _card_months_block(
            card,
            today,
            stats_filter,
            account_service=account_service,
        )

        payments = _collect_card_payments(card, period_start, period_end)
        pre_period_debt = _pre_period_debt_for_card(card, payments, months)
        _apply_payments_to_months(months, payments, pre_period_debt)
        schedule = _build_payment_schedule(months, history, card)
        total += _payment_schedule_remaining_debt(schedule)

    return total


def _credit_cards_block(
    accounts: QuerySet[Account],
    stats_filter: StatisticsFilters,
    account_service: AccountServiceProtocol,
) -> list[CreditCardDataDict]:
    out: list[CreditCardDataDict] = []
    today = timezone.now().date()
    today_month = today.replace(day=1)
    period_start, period_end = stats_filter.date_range(today)

    credit_cards = accounts.filter(
        type_account__in=[ACCOUNT_TYPE_CREDIT_CARD, ACCOUNT_TYPE_CREDIT],
    )

    for card in credit_cards:
        debt_now = account_service.get_credit_card_debt(card)
        months, history = _card_months_block(
            card,
            today,
            stats_filter,
            account_service=account_service,
        )

        payments = _collect_card_payments(card, period_start, period_end)
        pre_period_debt = _pre_period_debt_for_card(card, payments, months)
        _apply_payments_to_months(months, payments, pre_period_debt)
        schedule = _build_payment_schedule(months, history, card)

        current_info = account_service.calculate_grace_period_info(
            card,
            today_month,
        )
        current_info['debt_for_month'] = Decimal(
            str(
                max(
                    0,
                    current_info.get('debt_for_month', 0),
                ),
            ),
        )
        current_info['final_debt'] = Decimal(
            str(
                max(
                    0,
                    current_info.get('final_debt', 0),
                ),
            ),
        )

        limit_left = Decimal(str((card.limit_credit or 0) - (debt_now or 0)))

        out.append(
            {
                'name': card.name_account,
                'limit': card.limit_credit,
                'debt_now': debt_now,
                'current_grace_info': current_info,
                'history': history,
                'currency': card.currency,
                'card_obj': card,
                'limit_left': limit_left,
                'payment_schedule': schedule,
                'utilization_chart': _credit_card_utilization_chart(
                    history,
                    card.limit_credit,
                ),
                'utilization_chart_id': f'credit-utilization-{card.pk}',
                'minimum_payment_forecast': _minimum_payment_forecast(
                    _payment_schedule_remaining_debt(schedule),
                ),
            },
        )
    return out


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def get_user_detailed_statistics(
    user: User,
    container: 'ApplicationContainer',
    stats_filter: StatisticsFilters,
    request: Any | None = None,
    members: list[User] | None = None,
) -> UserDetailedStatisticsDict:
    """Получение детальной статистики пользователя с кешированием.

    Args:
        user: Пользователь для которого собирается статистика
        container: DI контейнер приложения
        stats_filter: Параметры фильтрации
        request: HTTP запрос (опционально)
        members: Список пользователей (опционально)

    Returns:
        Словарь с детальной статистикой пользователя
    """
    cache_key = get_user_detailed_statistics_cache_key(
        user.pk,
        stats_filter.cache_suffix,
    )
    cached_stats = cache.get(cache_key)

    if cached_stats is not None:
        return cached_stats  # type: ignore[no-any-return]

    now = timezone.now()
    today = now.date()
    period_start, period_end = stats_filter.date_range(today)
    users = members or _resolve_statistics_members(user, stats_filter)

    months_data = _six_months_data(
        users,
        today,
        stats_filter,
    )
    budgets_data = _budgets_data(users, period_start, period_end)
    top_expense_categories = _top_categories_with_comparison(
        TransactionType.EXPENSE,
        users,
        stats_filter,
        period_start,
        period_end,
    )
    top_income_categories = _top_categories_with_comparison(
        TransactionType.INCOME,
        users,
        stats_filter,
        period_start,
        period_end,
    )

    start_dt = _date_to_aware(period_start)
    end_dt = _date_to_aware(period_end, end_of_day=True)
    receipt_info_by_month = collect_info_receipt(
        user=user,
        users=users,
        start=start_dt,
        end=end_dt,
        account_ids=stats_filter.account_ids,
        currency=stats_filter.currency,
        category_keys=stats_filter.category_keys,
    )
    receipt_page = _paginate(
        _filtered_receipts(users, stats_filter, period_start, period_end)
        .select_related('account', 'user', 'seller')
        .order_by(stats_filter.receipts_sort),
        stats_filter.receipts_page,
    )
    (
        top_receipt_products,
        top_receipt_sellers,
        average_receipts_by_month,
    ) = _receipt_details(users, stats_filter, period_start, period_end)

    income_category_ids = _category_ids(
        stats_filter.category_keys,
        'income-',
    )
    expense_category_ids = _category_ids(
        stats_filter.category_keys,
        'expense-',
    )
    incomes = (
        collect_info_income(
            user,
            users=users,
            start=start_dt,
            end=end_dt,
            account_ids=stats_filter.account_ids,
            currency=stats_filter.currency,
            category_ids=income_category_ids,
        )
        if not stats_filter.category_keys or income_category_ids
        else []
    )
    for it in incomes:
        it['type'] = 'income'  # type: ignore[typeddict-unknown-key]

    expenses = (
        collect_info_expense(
            user,
            users=users,
            start=start_dt,
            end=end_dt,
            account_ids=stats_filter.account_ids,
            currency=stats_filter.currency,
            category_ids=expense_category_ids,
        )
        if not stats_filter.category_keys or expense_category_ids
        else []
    )
    for it in expenses:
        it['type'] = 'expense'  # type: ignore[typeddict-unknown-key]

    income_expense = sort_expense_income(expenses, incomes)
    reverse_operations = stats_filter.operations_sort.startswith('-')
    operations_sort_key = stats_filter.operations_sort.removeprefix('-')
    income_expense = sorted(
        income_expense,
        key=lambda item: item[operations_sort_key],
        reverse=reverse_operations,
    )
    if stats_filter.operations_search:
        income_expense = [
            item
            for item in income_expense
            if _match_income_expense_search(
                item,
                stats_filter.operations_search,
            )
        ]
    income_expense_page = _paginate(
        income_expense,
        stats_filter.operations_page,
    )

    transfer_money_log = _transfer_logs(
        users,
        stats_filter,
        period_start,
        period_end,
    ).order_by(stats_filter.transfers_sort)

    account_choices = Account.objects.filter(user__in=users).select_related(
        'user',
    )
    accounts = _filtered_accounts(account_choices, stats_filter)
    balances_by_currency, delta_by_currency = _balances_and_delta(
        accounts,
        today,
    )

    account_service = container.core.account_service()
    credit_cards_data = _credit_cards_block(
        accounts,
        stats_filter=stats_filter,
        account_service=account_service,
    )
    cashflow_forecast = build_cashflow_forecast(
        users=users,
        accounts=accounts,
        today=today,
    )
    chart_combined = _build_chart(
        users,
        stats_filter,
        period_start,
        period_end,
        forecast=cashflow_forecast,
    )
    payment_calendar = build_payment_calendar(
        users=users,
        credit_cards=credit_cards_data,
        today=today,
    )
    credit_cards_summary = _credit_cards_summary(credit_cards_data)
    statistics_alerts = _statistics_alerts(
        users,
        stats_filter,
        budgets_data,
        credit_cards_data,
        today,
    )
    currency_choices = sorted(
        set(account_choices.values_list('currency', flat=True)),
    )

    stats = {
        'months_data': months_data,
        'budgets_data': budgets_data,
        'top_expense_categories': top_expense_categories,
        'top_income_categories': top_income_categories,
        'receipt_info_by_month': receipt_info_by_month,
        'receipt_page': receipt_page,
        'top_receipt_products': top_receipt_products,
        'top_receipt_sellers': top_receipt_sellers,
        'average_receipts_by_month': average_receipts_by_month,
        'income_expense': income_expense,
        'income_expense_page': income_expense_page,
        'transfer_money_log': transfer_money_log,
        'transfer_money_log_page': _paginate(
            transfer_money_log,
            stats_filter.transfers_page,
        ),
        'accounts': accounts,
        'balances_by_currency': dict(balances_by_currency),
        'delta_by_currency': delta_by_currency,
        'chart_combined': chart_combined,
        'chart_combined_json': json.dumps(chart_combined),
        'user': user,
        'credit_cards_data': credit_cards_data,
        'credit_cards_summary': credit_cards_summary,
        'statistics_filter': stats_filter,
        'statistics_period_choices': _period_choices(),
        'statistics_account_choices': account_choices,
        'statistics_currency_choices': currency_choices,
        'statistics_category_choices': _category_choices(users),
        'statistics_member_choices': _member_choices(user, request),
        'statistics_members': users,
        'statistics_alerts': statistics_alerts,
        'payment_calendar': payment_calendar,
    }

    cache.set(cache_key, stats, 600)

    return stats  # type: ignore[return-value]


__all__ = [
    'CardHistoryDict',
    'CardMonthDict',
    'ChartDataDict',
    'CreditCardDataDict',
    'CreditCardSummaryDict',
    'DeltaByCurrencyDict',
    'IncomeExpenseDict',
    'PaymentItemDict',
    'PaymentScheduleItemDict',
    'UserDetailedStatisticsDict',
    '_apply_payments_to_months',
    '_balances_and_delta',
    '_build_chart',
    '_build_expenses_receipts_dicts',
    '_build_payment_schedule',
    '_build_single_card_month',
    '_calculate_grace_period_end',
    '_card_months_block',
    '_collect_card_payments',
    '_credit_card_utilization_chart',
    '_credit_cards_block',
    '_credit_cards_summary',
    '_dates_amounts',
    '_minimum_payment_forecast',
    '_paginate',
    '_payment_schedule_remaining_debt',
    '_pre_period_debt_for_card',
    '_statistics_alerts',
    'compute_total_payment_schedule_debt',
    'get_user_detailed_statistics',
]
