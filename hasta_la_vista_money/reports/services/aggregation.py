from calendar import monthrange
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from django.core.cache import cache
from django.db.models import CharField, F, Sum
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone
from typing_extensions import TypedDict

from hasta_la_vista_money import constants
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.users.services.cache import (
    get_reports_budget_charts_cache_key,
)


class BudgetChartsDict(TypedDict):
    """Budget chart data."""

    chart_labels: list[str]
    chart_income: list[float]
    chart_expense: list[float]
    chart_balance: list[float]
    pie_labels: list[str]
    pie_values: list[float]
    total_income: float
    total_expense: float
    net_balance: float
    savings_rate: float
    top_expense_category: str
    chart_start_dates: list[str]
    chart_end_dates: list[str]
    pie_category_keys: list[str]


def report_period_range(period: str) -> tuple[date, date] | None:
    """Return date range for the reports period filter."""
    today = timezone.localdate()
    if period == 'm':
        return today.replace(day=1), _end_of_month(today)
    if period == 'q':
        quarter = (today.month - 1) // 3
        start = date(today.year, quarter * 3 + 1, 1)
        return start, _end_of_month(date(today.year, quarter * 3 + 3, 1))
    if period == 'y':
        return date(today.year, 1, 1), date(today.year, 12, 31)
    return None


def _end_of_month(value: date) -> date:
    _, last_day = monthrange(value.year, value.month)
    return value.replace(day=last_day)


def collect_datasets(
    user: User,
) -> tuple[Any, Any]:
    """Collect expense and income datasets for user."""
    expense_dataset = (
        Transaction.objects.filter(user=user, type=TransactionType.EXPENSE)
        .values('date')
        .annotate(total_amount=Sum('amount'))
        .order_by('date')
    )
    income_dataset = (
        Transaction.objects.filter(user=user, type=TransactionType.INCOME)
        .values('date')
        .annotate(total_amount=Sum('amount'))
        .order_by('date')
    )
    return expense_dataset, income_dataset


def transform_dataset(
    dataset: Any,
) -> tuple[list[str], list[float]]:
    """Transform dataset to lists of dates and amounts."""
    dates: list[str] = []
    amounts: list[float] = []
    for item in dataset:
        date_value = item['date']
        if hasattr(date_value, 'strftime'):
            dates.append(date_value.strftime('%Y-%m-%d'))
        else:
            dates.append(str(date_value))
        amounts.append(float(item['total_amount']))
    return dates, amounts


def unique_aggregate(
    dates: list[str],
    amounts: list[float],
) -> tuple[list[str], list[float]]:
    """Aggregate amounts for unique dates."""
    aggregated: dict[str, float] = {}
    for idx, current_date in enumerate(dates):
        aggregated[current_date] = (
            aggregated.get(current_date, 0.0) + amounts[idx]
        )
    return list(aggregated.keys()), list(aggregated.values())


class SubcategoryDataDict(TypedDict):
    """Subcategory data for chart."""

    name: str
    y: float


class ChartDataPointDict(TypedDict):
    """Chart data point."""

    name: str
    y: float
    drilldown: str


class DrilldownSeriesDict(TypedDict):
    """Drilldown data series."""

    id: str
    name: str
    data: list[SubcategoryDataDict]


class ChartDataDict(TypedDict):
    """Category chart data."""

    parent_category: str
    data: list[ChartDataPointDict]
    drilldown_series: list[DrilldownSeriesDict]


def pie_expense_category(user: User) -> list[ChartDataDict]:
    """Return pie chart data for expense categories with monthly drilldown."""
    expense_rows = (
        Transaction.objects.filter(user=user, type=TransactionType.EXPENSE)
        .annotate(
            month=TruncMonth('date'),
            parent_category_name=Coalesce(
                F('category__parent_category__name'),
                F('category__name'),
                output_field=CharField(),
            ),
        )
        .values(
            'month',
            'parent_category_name',
            'category__name',
            'category__parent_category',
        )
        .annotate(total_amount=Sum('amount'))
        .order_by('parent_category_name', 'month', 'category__name')
    )

    grouped_chart_data: dict[str, dict[str, Any]] = {}

    for row in expense_rows:
        month_value = row['month']
        parent_category_name = row['parent_category_name']

        if month_value is None or not isinstance(parent_category_name, str):
            continue

        month_label = month_value.strftime('%B %Y')
        drilldown_id = f'{parent_category_name}_{month_label}'
        category_name = row['category__name']
        amount = float(row['total_amount'] or 0)

        chart_entry = grouped_chart_data.setdefault(
            parent_category_name,
            {'data': {}, 'drilldown_series': {}},
        )
        chart_entry['data'][month_label] = (
            chart_entry['data'].get(month_label, 0.0) + amount
        )

        if row['category__parent_category']:
            drilldown_series = chart_entry['drilldown_series'].setdefault(
                drilldown_id,
                [],
            )
            drilldown_series.append(
                {'name': category_name, 'y': amount},
            )

    charts: list[ChartDataDict] = []
    for parent_category, chart_data in grouped_chart_data.items():
        month_data = chart_data['data']
        drilldown_data = chart_data['drilldown_series']
        data = [
            ChartDataPointDict(
                name=month_label,
                y=month_total,
                drilldown=f'{parent_category}_{month_label}',
            )
            for month_label, month_total in month_data.items()
        ]
        drilldown_series: list[DrilldownSeriesDict] = []
        for drilldown_id, series_data in drilldown_data.items():
            month_label = drilldown_id.removeprefix(f'{parent_category}_')
            drilldown_series.append(
                DrilldownSeriesDict(
                    id=drilldown_id,
                    name=(
                        f'Subcategories for {parent_category} in {month_label}'
                    ),
                    data=series_data,
                ),
            )
        charts.append(
            ChartDataDict(
                parent_category=parent_category,
                data=data,
                drilldown_series=drilldown_series,
            ),
        )
    return charts


def _fact_map_for_categories(
    user: User,
    type_value: str,
    categories: Sequence[Category],
    months: list[date],
) -> dict[int, dict[date, Decimal]]:
    """Aggregate transactions per category and month."""
    fact_map: dict[int, dict[date, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal(0)),
    )
    if not months:
        return fact_map

    first_month = months[0]
    last_month = months[-1]

    first_month_start = timezone.make_aware(
        datetime.combine(
            date(first_month.year, first_month.month, 1),
            time.min,
        ),
    )

    _, last_day_last = monthrange(last_month.year, last_month.month)
    last_month_end = timezone.make_aware(
        datetime.combine(
            date(last_month.year, last_month.month, last_day_last),
            time.max,
        ),
    )

    qs = (
        Transaction.objects.filter(
            user=user,
            type=type_value,
            category__in=categories,
            date__gte=first_month_start,
            date__lte=last_month_end,
        )
        .annotate(month=TruncMonth('date'))
        .values('category_id', 'month')
        .annotate(total=Sum('amount'))
    )

    for row in qs:
        month_datetime = row['month']
        if isinstance(month_datetime, datetime) or hasattr(
            month_datetime,
            'date',
        ):
            month_date = month_datetime.date()
        else:
            month_date = month_datetime

        if isinstance(month_date, date) and month_date in months:
            total_amount = row['total'] or Decimal(0)
            fact_map[row['category_id']][month_date] = total_amount
    return fact_map


def _totals_by_month(
    categories: Sequence[Category],
    months: list[date],
    fact_map: dict[int, dict[date, Decimal]],
) -> list[float]:
    totals: list[Decimal] = [Decimal(0)] * len(months)
    for i, m in enumerate(months):
        for cat in categories:
            totals[i] += fact_map[cat.pk][m]
    return [float(x) for x in totals]


def _pie_for_categories(
    categories: Sequence[Category],
    months: list[date],
    fact_map: dict[int, dict[date, Decimal]],
) -> tuple[list[str], list[float], list[str]]:
    """Return labels and values for the expense pie chart."""
    labels: list[str] = []
    values: list[float] = []
    category_keys: list[str] = []
    if not months or not categories:
        return labels, values, category_keys
    totals: dict[int, Decimal] = defaultdict(lambda: Decimal(0))
    for cat in categories:
        for month in months:
            totals[cat.pk] += fact_map[cat.pk][month]
    for cat in categories:
        total = totals[cat.pk]
        if total > 0:
            labels.append(cat.name)
            values.append(float(total))
            category_keys.append(f'{TransactionType.EXPENSE}-{cat.pk}')
    return labels, values, category_keys


def budget_charts(user: User, period: str = 'y') -> BudgetChartsDict:
    """Build chart data for the reports dashboard."""
    cache_key = f'{get_reports_budget_charts_cache_key(user.pk)}:{period}'
    cached_charts = cache.get(cache_key)
    if cached_charts is not None:
        return cached_charts  # type: ignore[no-any-return]

    period_range = report_period_range(period)
    transactions_qs = Transaction.objects.filter(user=user)
    if period_range is not None:
        start, end = period_range
        transactions_qs = transactions_qs.filter(
            date__date__gte=start,
            date__date__lte=end,
        )

    months_qs = (
        transactions_qs.annotate(month=TruncMonth('date'))
        .values_list('month', flat=True)
        .distinct()
        .order_by('month')
    )

    all_months_set: set[date] = set()
    for d in months_qs:
        if d:
            month_date = d.date() if hasattr(d, 'date') else d
            if isinstance(month_date, date):
                all_months_set.add(month_date)

    months = sorted(all_months_set)

    expense_categories = list(
        user.categories.filter(type=TransactionType.EXPENSE).order_by('name'),
    )
    income_categories = list(
        user.categories.filter(type=TransactionType.INCOME).order_by('name'),
    )

    chart_labels = [m.strftime('%b %Y') for m in months] if months else []
    chart_start_dates = [m.isoformat() for m in months]
    chart_end_dates = [_end_of_month(m).isoformat() for m in months]

    expense_fact = _fact_map_for_categories(
        user,
        TransactionType.EXPENSE,
        expense_categories,
        months,
    )
    income_fact = _fact_map_for_categories(
        user,
        TransactionType.INCOME,
        income_categories,
        months,
    )

    total_expense = _totals_by_month(expense_categories, months, expense_fact)
    total_income = _totals_by_month(income_categories, months, income_fact)

    chart_balance = (
        [total_income[i] - total_expense[i] for i in range(len(months))]
        if months
        else []
    )

    pie_labels, pie_values, pie_category_keys = _pie_for_categories(
        expense_categories,
        months,
        expense_fact,
    )

    total_income_sum = sum(total_income)
    total_expense_sum = sum(total_expense)
    net_balance = total_income_sum - total_expense_sum
    savings_rate = (
        net_balance / total_income_sum * 100 if total_income_sum else 0.0
    )
    top_expense_category = (
        pie_labels[pie_values.index(max(pie_values))] if pie_values else ''
    )

    charts_data = {
        'chart_labels': chart_labels,
        'chart_income': total_income,
        'chart_expense': total_expense,
        'chart_balance': chart_balance,
        'pie_labels': pie_labels,
        'pie_values': pie_values,
        'total_income': total_income_sum,
        'total_expense': total_expense_sum,
        'net_balance': net_balance,
        'savings_rate': savings_rate,
        'top_expense_category': top_expense_category,
        'chart_start_dates': chart_start_dates,
        'chart_end_dates': chart_end_dates,
        'pie_category_keys': pie_category_keys,
    }
    cache.set(cache_key, charts_data, constants.REPORTS_CACHE_TIMEOUT)
    return charts_data
