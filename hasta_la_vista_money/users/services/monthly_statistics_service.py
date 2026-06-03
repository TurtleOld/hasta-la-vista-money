from calendar import monthrange
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from dateutil.relativedelta import relativedelta
from django.core.cache import cache
from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from typing_extensions import TypedDict

if TYPE_CHECKING:
    from config.containers import ApplicationContainer

from hasta_la_vista_money import constants
from hasta_la_vista_money.budget.models import Budget, Planning
from hasta_la_vista_money.transactions.models import (
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import FamilyGroupMembership, User
from hasta_la_vista_money.users.services.cache import (
    get_dashboard_summary_cache_key,
)
from hasta_la_vista_money.users.services.groups import get_family_groups


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
    operations_page: int = 1
    transfers_page: int = 1
    receipts_page: int = 1
    operations_sort: str = '-date'
    transfers_sort: str = '-exchange_date'
    receipts_sort: str = '-receipt_date'
    operations_search: str = ''
    transfers_search: str = ''
    receipts_search: str = ''

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
            operations_page=_positive_int(query.get('operations_page')),
            transfers_page=_positive_int(query.get('transfers_page')),
            receipts_page=_positive_int(query.get('receipts_page')),
            operations_sort=_allowed_sort(
                query.get('operations_sort'),
                {'date', '-date', 'amount', '-amount'},
                '-date',
            ),
            transfers_sort=_allowed_sort(
                query.get('transfers_sort'),
                {'exchange_date', '-exchange_date', 'amount', '-amount'},
                '-exchange_date',
            ),
            receipts_sort=_allowed_sort(
                query.get('receipts_sort'),
                {
                    'receipt_date',
                    '-receipt_date',
                    'total_sum',
                    '-total_sum',
                },
                '-receipt_date',
            ),
            operations_search=query.get('operations_search', '').strip(),
            transfers_search=query.get('transfers_search', '').strip(),
            receipts_search=query.get('receipts_search', '').strip(),
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
                self.operations_page != 1,
                self.transfers_page != 1,
                self.receipts_page != 1,
                self.operations_sort != '-date',
                self.transfers_sort != '-exchange_date',
                self.receipts_sort != '-receipt_date',
                bool(self.operations_search),
                bool(self.transfers_search),
                bool(self.receipts_search),
            ),
        )

    @property
    def query_string(self) -> str:
        params: list[tuple[str, str | int]] = []
        optional_params = [
            ('period', self.period, self.period != '6'),
            (
                'date_from',
                (
                    self.date_from.strftime(
                        constants.HTML5_DATE_INPUT_FORMAT,
                    )
                    if self.date_from
                    else ''
                ),
                bool(self.date_from),
            ),
            (
                'date_to',
                (
                    self.date_to.strftime(
                        constants.HTML5_DATE_INPUT_FORMAT,
                    )
                    if self.date_to
                    else ''
                ),
                bool(self.date_to),
            ),
            ('currency', self.currency, bool(self.currency)),
            ('member', self.member, self.member != 'my'),
            (
                'operations_page',
                self.operations_page,
                self.operations_page != 1,
            ),
            ('transfers_page', self.transfers_page, self.transfers_page != 1),
            ('receipts_page', self.receipts_page, self.receipts_page != 1),
            (
                'operations_sort',
                self.operations_sort,
                self.operations_sort != '-date',
            ),
            (
                'transfers_sort',
                self.transfers_sort,
                self.transfers_sort != '-exchange_date',
            ),
            (
                'receipts_sort',
                self.receipts_sort,
                self.receipts_sort != '-receipt_date',
            ),
            (
                'operations_search',
                self.operations_search,
                bool(self.operations_search),
            ),
            (
                'transfers_search',
                self.transfers_search,
                bool(self.transfers_search),
            ),
            (
                'receipts_search',
                self.receipts_search,
                bool(self.receipts_search),
            ),
        ]
        params.extend(
            (name, value) for name, value, enabled in optional_params if enabled
        )
        params.extend(
            ('account', account_id) for account_id in self.account_ids
        )
        params.extend(
            ('category', category_key) for category_key in self.category_keys
        )
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


def _parse_filter_date(value: str | None) -> date | None:
    if not value:
        return None
    normalized_value = value.strip()
    try:
        if '/' in normalized_value:
            day, month, year = normalized_value.split('/')
            return date(int(year), int(month), int(day))
        return date.fromisoformat(normalized_value)
    except (TypeError, ValueError):
        return None


def _positive_int(value: str | None) -> int:
    if value and value.isdigit():
        return max(1, int(value))
    return 1


def _allowed_sort(
    value: str | None,
    allowed_values: set[str],
    default: str,
) -> str:
    if value in allowed_values:
        return value
    return default


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

    income_by_month: dict[date, float] = {}
    expense_by_month: dict[date, float] = {}
    for row in qs:
        month_date = row['month'].date().replace(day=1)
        value = float(row['total'] or 0)
        if row['planning_type'] == TransactionType.INCOME:
            income_by_month[month_date] = value
        else:
            expense_by_month[month_date] = value
    return income_by_month, expense_by_month


def _aggregate_amounts_by_month(
    type_value: str,
    users: Iterable[User],
    stats_filter: StatisticsFilters,
    start: date,
    end: date,
) -> dict[date, float]:
    """Aggregate transaction amounts by month for the given period."""
    from hasta_la_vista_money.users.services.category_statistics_service import (
        _filtered_transactions,
    )

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


def _sum_amount_for_period(
    type_value: str,
    users: Iterable[User],
    start: date,
    end: date,
    stats_filter: StatisticsFilters,
) -> float:
    from hasta_la_vista_money.users.services.category_statistics_service import (
        _filtered_transactions,
    )

    queryset = _filtered_transactions(
        type_value,
        users,
        stats_filter,
        start=start,
        end=end,
    )
    return float(queryset.aggregate(total=Sum('amount'))['total'] or 0)


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


class DashboardSummaryStatisticsDict(TypedDict):
    """Lean dashboard payload for the SPA widgets."""

    months_data: list[MonthDataDict]
    top_expense_categories: list[dict[str, Any]]


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

    from hasta_la_vista_money.users.services.category_statistics_service import (
        _top_categories_qs,
    )

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


# ---------------------------------------------------------------------------
# Re-exported from original location for internal cross-module use
# ---------------------------------------------------------------------------

__all__ = [
    'BudgetDataDict',
    'DashboardSummaryStatisticsDict',
    'MonthDataDict',
    'StatisticsChoiceDict',
    'StatisticsFilters',
    '_aggregate_amounts_by_month',
    '_allowed_sort',
    '_budgets_data',
    '_date_to_aware',
    '_family_users_for_statistics',
    '_member_choices',
    '_month_ranges_for_filter',
    '_normalize_member_filter',
    '_owned_family_group_ids',
    '_parse_filter_date',
    '_period_choices',
    '_planning_amounts_by_month',
    '_positive_int',
    '_resolve_statistics_members',
    '_six_months_data',
    '_sum_amount_for_period',
    'get_dashboard_summary_statistics',
]
