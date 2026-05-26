from calendar import monthrange
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from dateutil.relativedelta import relativedelta
from django.core.cache import cache
from django.db.models import Q, QuerySet, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from typing_extensions import TypedDict

from core.protocols.services import AccountServiceProtocol

if TYPE_CHECKING:
    from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.budget.models import Budget, Planning
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
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import FamilyGroupMembership, User
from hasta_la_vista_money.users.services.cache import (
    get_dashboard_summary_cache_key,
    get_user_detailed_statistics_cache_key,
)
from hasta_la_vista_money.users.services.groups import get_family_groups

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.services import (
        GracePeriodInfoDict,
    )


class MonthDataDict(TypedDict, total=False):
    """Month data.

    Attributes:
        month: Month identifier.
        expenses: Total expenses for month.
        income: Total income for month.
        savings: Savings for month.
        savings_percent: Savings percentage.
        balance: Balance for month.
        planned_income: Planned income for month.
        planned_expenses: Planned expenses for month.
        deviation: Actual savings minus planned savings.
    """

    month: str
    expenses: float
    income: float
    savings: float
    savings_percent: float
    balance: float
    month_start: str
    month_end: str
    planned_income: float
    planned_expenses: float
    deviation: float


class BudgetDataDict(TypedDict):
    """Budget vs actual data for a single budget limit.

    Attributes:
        category_name: Category name or 'Общий лимит'.
        period: Human-readable month string.
        amount_limit: Budget limit amount.
        actual_expenses: Actual expenses in this period/category.
        usage_percent: Percentage of limit used.
        alert_threshold: Warning threshold percentage.
        over_limit: Whether actual exceeds limit.
        near_limit: Whether actual is between threshold and limit.
    """

    category_name: str
    period: str
    amount_limit: float
    actual_expenses: float
    usage_percent: float
    alert_threshold: int
    over_limit: bool
    near_limit: bool


class ChartDataDict(TypedDict):
    """Chart data.

    Attributes:
        labels: List of chart labels.
        expense_data: List of expense values.
        income_data: List of income values.
    """

    labels: list[str]
    expense_data: list[float]
    income_data: list[float]


class DeltaByCurrencyDict(TypedDict, total=False):
    """Balance change by currency.

    Attributes:
        delta: Balance change amount.
        percent: Balance change percentage.
    """

    delta: float
    percent: float | None


class CardMonthDict(TypedDict):
    """Credit card month data.

    Attributes:
        month: Month identifier.
        purchase_start: Purchase period start.
        purchase_end: Purchase period end.
        grace_end: Grace period end date.
        debt_for_month: Debt for month.
        is_overdue: Whether payment is overdue.
        days_until_due: Days until payment due.
        payments_made: Payments made amount.
        remaining_debt: Remaining debt amount.
        is_paid: Whether month is paid.
    """

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
    """Credit card history by month.

    Attributes:
        month: Month identifier.
        debt: Debt amount.
        final_debt: Final debt amount.
        grace_end: Grace period end date.
        is_overdue: Whether payment is overdue.
    """

    month: str
    debt: float
    final_debt: float
    grace_end: str
    is_overdue: bool


class PaymentItemDict(TypedDict):
    """Payment item.

    Attributes:
        amount: Payment amount.
        date: Payment date.
    """

    amount: Decimal
    date: date


class PaymentScheduleItemDict(TypedDict):
    """Payment schedule item.

    Attributes:
        month: Month identifier.
        sum_expense: Total expenses for month.
        payments_made: Payments made amount.
        remaining_debt: Remaining debt amount.
        payment_due: Payment due date.
        is_overdue: Whether payment is overdue.
        days_until_due: Days until payment due.
        is_paid: Whether month is paid.
    """

    month: str
    sum_expense: float
    payments_made: float
    remaining_debt: float
    payment_due: str
    is_overdue: bool
    days_until_due: int
    is_paid: bool


class CreditCardDataDict(TypedDict, total=False):
    """Credit card data.

    Attributes:
        name: Card name.
        limit: Credit limit.
        debt_now: Current debt.
        current_grace_info: Current grace period info.
        history: Payment history.
        currency: Currency code.
        card_obj: Account instance.
        limit_left: Remaining credit limit.
        payment_schedule: Payment schedule.
    """

    name: str
    limit: Decimal | None
    debt_now: Decimal | None
    current_grace_info: 'GracePeriodInfoDict'
    history: list[CardHistoryDict]
    currency: str
    card_obj: Account
    limit_left: Decimal
    payment_schedule: list[PaymentScheduleItemDict]


class IncomeExpenseDict(TypedDict):
    """Income/expense data.

    Attributes:
        id: Transaction ID.
        date: Transaction date.
        account__name_account: Account name.
        category__name: Category name.
        amount: Transaction amount.
        type: Transaction type.
    """

    id: int
    date: date
    account__name_account: str
    category__name: str
    user__username: str
    amount: Decimal
    type: str


class DashboardSummaryStatisticsDict(TypedDict):
    """Lean dashboard payload for the SPA widgets."""

    months_data: list[MonthDataDict]
    top_expense_categories: list[dict[str, Any]]


class StatisticsChoiceDict(TypedDict):
    """Generic select option for the statistics filter form."""

    value: str
    label: str


@dataclass(frozen=True)
class StatisticsFilters:
    """GET parameters shared by all detailed statistics tabs."""

    period: str = '6'
    date_from: date | None = None
    date_to: date | None = None
    account_ids: list[int] = field(default_factory=list)
    currency: str = ''
    category_keys: list[str] = field(default_factory=list)
    member: str = 'my'

    @classmethod
    def from_query(cls, query: Any) -> 'StatisticsFilters':
        period = query.get('period', '6')
        if period not in {'month', '3', '6', '12', 'range'}:
            period = '6'
        return cls(
            period=period,
            date_from=_parse_filter_date(query.get('date_from')),
            date_to=_parse_filter_date(query.get('date_to')),
            account_ids=[
                int(value)
                for value in query.getlist('account')
                if value.isdigit()
            ],
            currency=query.get('currency', '').strip().upper(),
            category_keys=list(query.getlist('category')),
            member=_normalize_member_filter(query.get('member', 'my')),
        )

    @property
    def is_default(self) -> bool:
        return not any(
            (
                self.period != '6',
                self.date_from,
                self.date_to,
                self.account_ids,
                self.currency,
                self.category_keys,
                self.member != 'my',
            ),
        )

    @property
    def query_string(self) -> str:
        params: list[tuple[str, str | int]] = []
        if self.period != '6':
            params.append(('period', self.period))
        if self.date_from:
            params.append(('date_from', self.date_from.isoformat()))
        if self.date_to:
            params.append(('date_to', self.date_to.isoformat()))
        params.extend(
            ('account', account_id) for account_id in self.account_ids
        )
        if self.currency:
            params.append(('currency', self.currency))
        params.extend(
            ('category', category_key) for category_key in self.category_keys
        )
        if self.member != 'my':
            params.append(('member', self.member))
        return urlencode(params)

    @property
    def cache_suffix(self) -> str:
        return self.query_string or 'default'

    def date_range(self, today: date) -> tuple[date, date]:
        if self.period == 'range':
            start = self.date_from or date(2000, 1, 1)
            end = self.date_to or today
            return (end, start) if start > end else (start, end)
        if self.period == 'month':
            return today.replace(day=1), today

        months_count = int(self.period)
        start = today.replace(day=1) - relativedelta(
            months=months_count - constants.ONE,
        )
        return start, today


class UserDetailedStatisticsDict(TypedDict):
    """User detailed statistics.

    Attributes:
        months_data: Monthly data list.
        top_expense_categories: Top expense categories.
        top_income_categories: Top income categories.
        receipt_info_by_month: Receipts queryset by month.
        income_expense: Income/expense transactions.
        transfer_money_log: Transfer logs queryset.
        accounts: Accounts queryset.
        balances_by_currency: Balances by currency.
        delta_by_currency: Balance changes by currency.
        chart_combined: Combined chart data.
        user: User instance.
        credit_cards_data: Credit cards data list.
    """

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


def _parse_filter_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _normalize_member_filter(value: str | None) -> str:
    result = 'my'
    if value in {'my', 'family'}:
        result = value
    elif value == 'all':
        result = 'family'
    elif value and value.startswith('user-'):
        user_id = value.removeprefix('user-')
        if user_id.isdigit():
            result = value
    elif value and value.isdigit():
        result = f'user-{value}'
    return result


def _date_to_aware(value: date, *, end_of_day: bool = False) -> datetime:
    edge = time.max if end_of_day else time.min
    return timezone.make_aware(datetime.combine(value, edge))


def _month_ranges_for_filter(
    today: date,
    stats_filter: StatisticsFilters,
) -> list[tuple[date, date, date]]:
    start, end = stats_filter.date_range(today)
    first_month = start.replace(day=1)
    last_month = end.replace(day=1)

    ranges = []
    current = first_month
    while current <= last_month:
        last_day = monthrange(current.year, current.month)[1]
        month_end = current.replace(day=last_day)
        ranges.append((current, max(current, start), min(month_end, end)))
        current = current + relativedelta(months=constants.ONE)
    return ranges


def _period_choices() -> list[StatisticsChoiceDict]:
    return [
        {'value': 'month', 'label': 'Текущий месяц'},
        {'value': '3', 'label': '3 месяца'},
        {'value': '6', 'label': '6 месяцев'},
        {'value': '12', 'label': '12 месяцев'},
        {'value': 'range', 'label': 'Диапазон'},
    ]


def _owned_family_group_ids(user: User) -> list[int]:
    return list(
        FamilyGroupMembership.objects.filter(
            user=user,
            role=FamilyGroupMembership.Role.OWNER,
        ).values_list('group_id', flat=True),
    )


def _family_users_for_statistics(user: User) -> list[User]:
    group_ids = _owned_family_group_ids(user)
    if not group_ids:
        return [user]
    return list(
        User.objects.filter(family_memberships__group_id__in=group_ids)
        .distinct()
        .order_by('username'),
    ) or [user]


def _resolve_statistics_members(
    user: User,
    stats_filter: StatisticsFilters,
) -> list[User]:
    if stats_filter.member == 'my':
        return [user]

    family_users = _family_users_for_statistics(user)
    if stats_filter.member == 'family':
        return family_users
    if stats_filter.member.startswith('user-'):
        user_id = stats_filter.member.removeprefix('user-')
        if user_id.isdigit():
            selected = [
                member for member in family_users if member.pk == int(user_id)
            ]
            if selected:
                return selected
    return [user]


def _member_choices(
    user: User,
    request: Any | None,
) -> list[StatisticsChoiceDict]:
    if request is None:
        return [{'value': 'my', 'label': 'Мои данные'}]

    family_groups = get_family_groups(user, request)
    has_owned_family = any(
        group['role'] == FamilyGroupMembership.Role.OWNER
        for group in family_groups
    )
    family_users = _family_users_for_statistics(user)
    choices = [
        {'value': 'my', 'label': 'Мои данные'},
    ]
    if has_owned_family:
        choices.append({'value': 'family', 'label': 'Вся семья'})
    choices.extend(
        {'value': f'user-{member.pk}', 'label': member.username}
        for member in family_users
        if has_owned_family or member.pk == user.pk
    )
    return choices


def _category_ids(keys: list[str], prefix: str) -> list[int]:
    return [
        int(value.removeprefix(prefix))
        for value in keys
        if value.startswith(prefix) and value.removeprefix(prefix).isdigit()
    ]


def _filter_transaction_queryset(
    queryset: QuerySet[Transaction],
    *,
    stats_filter: StatisticsFilters,
    type_value: str,
    start: date | None = None,
    end: date | None = None,
) -> QuerySet[Transaction]:
    if start is not None:
        queryset = queryset.filter(date__gte=_date_to_aware(start))
    if end is not None:
        queryset = queryset.filter(
            date__lte=_date_to_aware(end, end_of_day=True)
        )
    if stats_filter.account_ids:
        queryset = queryset.filter(account_id__in=stats_filter.account_ids)
    if stats_filter.currency:
        queryset = queryset.filter(account__currency=stats_filter.currency)

    category_ids = _category_ids(stats_filter.category_keys, f'{type_value}-')
    if category_ids:
        queryset = queryset.filter(category_id__in=category_ids)
    elif stats_filter.category_keys:
        queryset = queryset.none()
    return queryset


def _filtered_transactions(
    type_value: str,
    users: Iterable[User],
    stats_filter: StatisticsFilters,
    start: date | None = None,
    end: date | None = None,
) -> QuerySet[Transaction]:
    queryset = Transaction.objects.filter(user__in=users, type=type_value)
    return _filter_transaction_queryset(
        queryset,
        stats_filter=stats_filter,
        type_value=type_value,
        start=start,
        end=end,
    )


def _filtered_receipts(
    users: Iterable[User],
    stats_filter: StatisticsFilters,
    start: date,
    end: date,
    account: Account | None = None,
) -> QuerySet[Receipt]:
    queryset = Receipt.objects.filter(
        user__in=users,
        receipt_date__gte=_date_to_aware(start),
        receipt_date__lte=_date_to_aware(end, end_of_day=True),
    )
    if account is not None:
        queryset = queryset.filter(account=account)
    if stats_filter.account_ids:
        queryset = queryset.filter(account_id__in=stats_filter.account_ids)
    if stats_filter.currency:
        queryset = queryset.filter(account__currency=stats_filter.currency)
    if (
        stats_filter.category_keys
        and 'receipt' not in stats_filter.category_keys
    ):
        queryset = queryset.none()
    return queryset


def _filtered_accounts(
    accounts: QuerySet[Account],
    stats_filter: StatisticsFilters,
) -> QuerySet[Account]:
    if stats_filter.account_ids:
        accounts = accounts.filter(pk__in=stats_filter.account_ids)
    if stats_filter.currency:
        accounts = accounts.filter(currency=stats_filter.currency)
    return accounts


def _category_choices(users: Iterable[User]) -> list[StatisticsChoiceDict]:
    choices = [
        {
            'value': f'{category.type}-{category.pk}',
            'label': f'{category.name} ({category.get_type_display()})',
        }
        for category in Category.objects.filter(user__in=users).order_by(
            'type',
            'name',
        )
    ]
    choices.append({'value': 'receipt', 'label': 'Чеки'})
    return choices


def _transfer_logs(
    users: Iterable[User],
    stats_filter: StatisticsFilters,
    start: date,
    end: date,
) -> QuerySet[TransferMoneyLog]:
    if stats_filter.category_keys:
        return TransferMoneyLog.objects.none()

    queryset = (
        TransferMoneyLog.objects.filter(
            user__in=users,
            exchange_date__gte=_date_to_aware(start),
            exchange_date__lte=_date_to_aware(end, end_of_day=True),
        )
        .select_related('to_account', 'from_account', 'user')
        .order_by('-exchange_date')
    )
    if stats_filter.account_ids:
        queryset = queryset.filter(
            Q(from_account_id__in=stats_filter.account_ids)
            | Q(to_account_id__in=stats_filter.account_ids),
        )
    if stats_filter.currency:
        queryset = queryset.filter(
            Q(from_account__currency=stats_filter.currency)
            | Q(to_account__currency=stats_filter.currency),
        )
    return queryset


def _sum_amount_for_period(
    type_value: str,
    users: Iterable[User],
    start: date,
    end: date,
    stats_filter: StatisticsFilters,
) -> float:
    queryset = _filtered_transactions(
        type_value,
        users,
        stats_filter,
        start=start,
        end=end,
    )
    return float(queryset.aggregate(total=Sum('amount'))['total'] or 0)


def _top_categories_qs(
    type_value: str,
    users: Iterable[User],
    stats_filter: StatisticsFilters,
    start: date,
    end: date,
) -> Any:
    queryset = _filtered_transactions(
        type_value,
        users,
        stats_filter,
        start=start,
        end=end,
    )
    return (
        queryset.values('category__id', 'category__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')[: constants.TOP_CATEGORIES_LIMIT]
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
        return {'labels': [], 'expense_data': [], 'income_data': []}

    exp_series = [exp_map.get(d, constants.ZERO) for d in all_dates]
    inc_series = [inc_map.get(d, constants.ZERO) for d in all_dates]

    if len(all_dates) == constants.ONE:
        d = date.fromisoformat(all_dates[0])
        dt = datetime.combine(d, time.min)
        aware = timezone.make_aware(dt)
        prev = (aware - timedelta(days=constants.ONE)).date().isoformat()

        all_dates = [prev, *all_dates]
        exp_series = [constants.ZERO, *exp_series]
        inc_series = [constants.ZERO, *inc_series]

    return {
        'labels': all_dates,
        'expense_data': exp_series,
        'income_data': inc_series,
    }


def get_dashboard_summary_statistics(
    user: User,
    container: 'ApplicationContainer',
) -> DashboardSummaryStatisticsDict:
    """Return the dashboard widget payload without heavyweight sections."""
    del container

    cache_key = get_dashboard_summary_cache_key(user.pk)
    cached_stats = cache.get(cache_key)

    if cached_stats is not None:
        return cached_stats  # type: ignore[no-any-return]

    now = timezone.now()
    today = now.date()
    stats_filter = StatisticsFilters()
    start, end = stats_filter.date_range(today)
    users = [user]

    stats: DashboardSummaryStatisticsDict = {
        'months_data': _six_months_data(
            users,
            today,
            stats_filter,
        ),
        'top_expense_categories': list(
            _top_categories_qs(
                TransactionType.EXPENSE,
                users,
                stats_filter,
                start,
                end,
            ),
        ),
    }

    cache.set(cache_key, stats, constants.DASHBOARD_CACHE_TIMEOUT)
    return stats


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


def _planning_amounts_by_month(
    users: Iterable[User],
    period_start: date,
    period_end: date,
) -> tuple[dict[date, float], dict[date, float]]:
    """Aggregate planned income and expense amounts by month."""
    qs = (
        Planning.objects.filter(
            user__in=list(users),
            date__range=(period_start, period_end),
        )
        .select_related(None)
        .annotate(month=TruncMonth('date'))
        .values('month', 'planning_type')
        .annotate(total=Sum('amount'))
    )
    income: dict[date, float] = {}
    expense: dict[date, float] = {}
    for item in qs:
        if item['month'] is None:
            continue
        m: date = (
            item['month'].date()
            if hasattr(item['month'], 'date')
            else item['month']
        )
        total = float(item['total'] or 0)
        if item['planning_type'] == TransactionType.INCOME:
            income[m] = income.get(m, 0.0) + total
        else:
            expense[m] = expense.get(m, 0.0) + total
    return income, expense


def _six_months_data(
    users: Iterable[User],
    today: date,
    stats_filter: StatisticsFilters,
) -> list[MonthDataDict]:
    out = []

    month_ranges = _month_ranges_for_filter(today, stats_filter)
    if month_ranges:
        period_start = month_ranges[0][1]
        period_end = month_ranges[-1][2]
        expense_by_month = _aggregate_amounts_by_month(
            TransactionType.EXPENSE,
            users,
            stats_filter,
            period_start,
            period_end,
        )
        income_by_month = _aggregate_amounts_by_month(
            TransactionType.INCOME,
            users,
            stats_filter,
            period_start,
            period_end,
        )
        planned_income_by_month, planned_expense_by_month = (
            _planning_amounts_by_month(
                users,
                period_start,
                period_end,
            )
        )
    else:
        expense_by_month = {}
        income_by_month = {}
        planned_income_by_month = {}
        planned_expense_by_month = {}

    for m_start, range_start, range_end in month_ranges:
        exp_sum = expense_by_month.get(m_start, 0.0)
        inc_sum = income_by_month.get(m_start, 0.0)
        plan_inc = planned_income_by_month.get(m_start, 0.0)
        plan_exp = planned_expense_by_month.get(m_start, 0.0)
        out.append(
            {
                'month': m_start.strftime('%B %Y'),
                'expenses': exp_sum,
                'income': inc_sum,
                'savings': inc_sum - exp_sum,
                'month_start': range_start.isoformat(),
                'month_end': range_end.isoformat(),
                'planned_income': plan_inc,
                'planned_expenses': plan_exp,
                'deviation': (inc_sum - exp_sum) - (plan_inc - plan_exp),
            },
        )

    if out:
        first_month_start = str(out[0]['month_start'])
        first_month_start_date = date.fromisoformat(first_month_start)
        period_end_date: date = first_month_start_date - timedelta(days=1)

        total_income_before = _sum_amount_for_period(
            TransactionType.INCOME,
            users,
            date(2000, 1, 1),
            period_end_date,
            stats_filter,
        )
        total_expense_before = _sum_amount_for_period(
            TransactionType.EXPENSE,
            users,
            date(2000, 1, 1),
            period_end_date,
            stats_filter,
        )

        running_balance = total_income_before - total_expense_before
    else:
        running_balance = 0.0

    for m in out:
        income_raw = m.get('income', 0.0) or 0.0
        expenses_raw = m.get('expenses', 0.0) or 0.0
        savings_raw = m.get('savings', 0.0) or 0.0
        income_val = (
            float(income_raw)
            if isinstance(income_raw, int | float | str)
            else 0.0
        )
        expenses_val = (
            float(expenses_raw)
            if isinstance(expenses_raw, int | float | str)
            else 0.0
        )
        savings_val = (
            float(savings_raw)
            if isinstance(savings_raw, int | float | str)
            else 0.0
        )
        m['savings_percent'] = (
            savings_val / income_val * constants.PERCENTAGE_MULTIPLIER
            if income_val > constants.ZERO
            else float(constants.ZERO)
        )

        running_balance = running_balance + income_val - expenses_val
        m['balance'] = round(running_balance, 2)
    return out  # type: ignore[return-value]


def _budgets_data(
    users: Iterable[User],
    period_start: date,
    period_end: date,
) -> list[BudgetDataDict]:
    """Build budget vs actual data for all budgets within the period."""
    users_list = list(users)
    budgets = (
        Budget.objects.filter(
            user__in=users_list,
            period__gte=period_start.replace(day=1),
            period__lte=period_end.replace(day=1),
        )
        .select_related('category')
        .order_by('period', 'category__name')
    )

    result: list[BudgetDataDict] = []
    for budget in budgets:
        month_start = budget.period
        last_day = monthrange(month_start.year, month_start.month)[1]
        month_end = month_start.replace(day=last_day)

        expense_qs = Transaction.objects.filter(
            user__in=users_list,
            type=TransactionType.EXPENSE,
            date__gte=_date_to_aware(month_start),
            date__lte=_date_to_aware(month_end, end_of_day=True),
        )
        if budget.category_id:
            expense_qs = expense_qs.filter(category=budget.category)

        actual = float(
            expense_qs.aggregate(total=Sum('amount'))['total'] or 0,
        )
        limit = float(budget.amount_limit)
        usage_pct = (
            round(actual / limit * constants.PERCENTAGE_MULTIPLIER, 1)
            if limit > 0
            else 0.0
        )

        result.append(
            {
                'category_name': budget.category.name
                if budget.category_id
                else 'Общий лимит',
                'period': budget.period.strftime('%B %Y'),
                'amount_limit': limit,
                'actual_expenses': actual,
                'usage_percent': usage_pct,
                'alert_threshold': budget.alert_threshold,
                'over_limit': usage_pct >= constants.ONE_HUNDRED,
                'near_limit': usage_pct >= budget.alert_threshold
                and usage_pct < constants.ONE_HUNDRED,
            },
        )
    return result


def _aggregate_amounts_by_month(
    type_value: str,
    users: Iterable[User],
    stats_filter: StatisticsFilters,
    start: date,
    end: date,
) -> dict[date, float]:
    """Aggregate transaction amounts by month for the given period."""
    monthly_totals = (
        _filtered_transactions(
            type_value,
            users,
            stats_filter,
            start=start,
            end=end,
        )
        .annotate(month=TruncMonth('date'))
        .values('month')
        .annotate(total=Sum('amount'))
        .order_by('month')
    )

    return {
        item['month'].date(): float(item['total'] or 0)
        for item in monthly_totals
        if item['month'] is not None
    }


def _build_expenses_receipts_dicts(
    expenses_by_month: QuerySet[Transaction, dict[str, Any]],
    receipts_by_month: QuerySet[Receipt, dict[str, Any]],
) -> tuple[dict[date, Decimal], dict[date, dict[int, Decimal]]]:
    """Build expenses and receipts dictionaries by month.

    Args:
        expenses_by_month: QuerySet of expenses aggregated by month.
        receipts_by_month: QuerySet of receipts aggregated by month.

    Returns:
        Tuple of (expenses_dict, receipts_dict) where expenses_dict maps
        month date to total amount, and receipts_dict maps month date to
        operation_type->amount mapping.
    """
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


def _apply_payments_to_months(
    months: list[CardMonthDict],
    payments: list[PaymentItemDict],
) -> None:
    total = sum(float(p['amount']) for p in payments)
    left = total
    for m in months:
        debt = float(m['debt_for_month'])
        if debt <= constants.ZERO:
            m['payments_made'] = constants.ZERO
            m['remaining_debt'] = constants.ZERO
            m['is_paid'] = True
            continue
        paid = min(left, debt)
        m['payments_made'] = paid
        m['remaining_debt'] = max(debt - paid, constants.ZERO)
        m['is_paid'] = m['remaining_debt'] <= constants.ZERO
        left = max(left - paid, constants.ZERO)


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

        payments_raw = list(
            _filter_transaction_queryset(
                Transaction.objects.filter(
                    account=card,
                    user=card.user,
                    type=TransactionType.INCOME,
                ),
                stats_filter=stats_filter,
                type_value=TransactionType.INCOME,
                start=period_start,
                end=period_end,
            ).values('amount', 'date'),
        )
        payments: list[PaymentItemDict] = [
            {'amount': Decimal(str(p['amount'])), 'date': p['date']}
            for p in payments_raw
        ]
        _apply_payments_to_months(months, payments)
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
            },
        )
    return out


def get_user_detailed_statistics(
    user: User,
    container: 'ApplicationContainer',
    stats_filter: StatisticsFilters,
    request: Any | None = None,
    members: list[User] | None = None,
) -> UserDetailedStatisticsDict:
    """
    Получение детальной статистики пользователя с кешированием.

    Args:
        user: Пользователь для которого собирается статистика
        container: DI контейнер приложения

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
    top_expense_categories = _top_categories_qs(
        TransactionType.EXPENSE,
        users,
        stats_filter,
        period_start,
        period_end,
    )
    top_income_categories = _top_categories_qs(
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

    transfer_money_log = _transfer_logs(
        users,
        stats_filter,
        period_start,
        period_end,
    )

    account_choices = Account.objects.filter(user__in=users).select_related(
        'user',
    )
    accounts = _filtered_accounts(account_choices, stats_filter)
    balances_by_currency, delta_by_currency = _balances_and_delta(
        accounts,
        today,
    )

    chart_combined = _build_chart(
        users,
        stats_filter,
        period_start,
        period_end,
    )

    account_service = container.core.account_service()
    credit_cards_data = _credit_cards_block(
        accounts,
        stats_filter=stats_filter,
        account_service=account_service,
    )
    currency_choices = sorted(
        set(account_choices.values_list('currency', flat=True)),
    )

    stats = {
        'months_data': months_data,
        'budgets_data': budgets_data,
        'top_expense_categories': list(top_expense_categories),
        'top_income_categories': list(top_income_categories),
        'receipt_info_by_month': receipt_info_by_month,
        'income_expense': income_expense,
        'transfer_money_log': transfer_money_log,
        'accounts': accounts,
        'balances_by_currency': dict(balances_by_currency),
        'delta_by_currency': delta_by_currency,
        'chart_combined': chart_combined,
        'user': user,
        'credit_cards_data': credit_cards_data,
        'statistics_filter': stats_filter,
        'statistics_period_choices': _period_choices(),
        'statistics_account_choices': account_choices,
        'statistics_currency_choices': currency_choices,
        'statistics_category_choices': _category_choices(users),
        'statistics_member_choices': _member_choices(user, request),
        'statistics_members': users,
    }

    cache.set(cache_key, stats, 600)

    return stats  # type: ignore[return-value]
