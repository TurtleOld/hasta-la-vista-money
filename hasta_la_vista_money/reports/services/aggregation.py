from calendar import monthrange
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from typing_extensions import TypedDict

from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.users.models import User


class BudgetChartsDict(TypedDict):
    """Данные для графиков бюджета."""

    chart_labels: list[str]
    chart_income: list[float]
    chart_expense: list[float]
    chart_balance: list[float]
    pie_labels: list[str]
    pie_values: list[float]


def collect_datasets(
    user: User,
) -> tuple[Any, Any]:
    expense_dataset = (
        Expense.objects.filter(user=user)
        .values('date')
        .annotate(total_amount=Sum('amount'))
        .order_by('date')
    )
    income_dataset = (
        Income.objects.filter(user=user)
        .values('date')
        .annotate(total_amount=Sum('amount'))
        .order_by('date')
    )
    return expense_dataset, income_dataset


def transform_dataset(
    dataset: Any,
) -> tuple[list[str], list[float]]:
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
    unique_dates: list[str] = []
    unique_amounts: list[float] = []
    for idx, d in enumerate(dates):
        if d not in unique_dates:
            unique_dates.append(d)
            unique_amounts.append(amounts[idx])
        else:
            i = unique_dates.index(d)
            unique_amounts[i] += amounts[idx]
    return unique_dates, unique_amounts


class SubcategoryDataDict(TypedDict):
    """Данные подкатегории для графика."""

    name: str
    y: float


class ChartDataPointDict(TypedDict):
    """Точка данных на графике."""

    name: str
    y: float
    drilldown: str


class DrilldownSeriesDict(TypedDict):
    """Серия данных для детализации."""

    id: str
    name: str
    data: list[SubcategoryDataDict]


class ChartDataDict(TypedDict):
    """Данные для графика категорий."""

    parent_category: str
    data: list[ChartDataPointDict]
    drilldown_series: list[DrilldownSeriesDict]


def pie_expense_category(user: User) -> list[ChartDataDict]:
    expense_data: dict[str, dict[str, float]] = defaultdict(
        lambda: defaultdict(float),
    )
    subcategory_data: dict[str, list[SubcategoryDataDict]] = defaultdict(list)

    for expense in Expense.objects.filter(user=user).select_related(
        'category',
        'category__parent_category',
    ):
        parent_category_name = (
            expense.category.parent_category.name
            if expense.category.parent_category
            else expense.category.name
        )
        month = expense.date.strftime('%B %Y')
        amount = float(expense.amount or 0)
        expense_data[parent_category_name][month] += amount

        if expense.category.parent_category:
            key = f'{parent_category_name}_{month}'
            subcategory_data[key].append(
                {'name': expense.category.name, 'y': amount},
            )

    charts: list[ChartDataDict] = []
    for parent_category, subcats in expense_data.items():
        data: list[ChartDataPointDict] = [
            ChartDataPointDict(name=m, y=v, drilldown=f'{parent_category}_{m}')
            for m, v in subcats.items()
        ]
        drilldown_series: list[DrilldownSeriesDict] = [
            DrilldownSeriesDict(
                id=f'{parent_category}_{m}',
                name=f'Subcategories for {parent_category} in {m}',
                data=subcategory_data[f'{parent_category}_{m}'],
            )
            for m in subcats
        ]
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
    model: type[Expense | Income],
    categories: Sequence[ExpenseCategory | IncomeCategory],
    months: list[date],
) -> dict[int, dict[date, Decimal]]:
    fact_map: dict[int, dict[date, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal(0)),
    )
    if not months:
        return fact_map

    first_month = months[0]
    last_month = months[-1]

    first_month_start = timezone.make_aware(
        datetime(
            first_month.year,
            first_month.month,
            1,
            0,
            0,
            0,
            tzinfo=timezone.utc,
        ),
    )

    _, last_day_last = monthrange(last_month.year, last_month.month)
    last_month_end = timezone.make_aware(
        datetime(
            last_month.year,
            last_month.month,
            last_day_last,
            23,
            59,
            59,
            999999,
            tzinfo=timezone.utc,
        ),
    )

    qs = (
        model.objects.filter(
            user=user,
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
    categories: Sequence[ExpenseCategory | IncomeCategory],
    months: list[date],
    fact_map: dict[int, dict[date, Decimal]],
) -> list[float]:
    totals: list[Decimal] = [Decimal(0)] * len(months)
    for i, m in enumerate(months):
        for cat in categories:
            totals[i] += fact_map[cat.pk][m]
    return [float(x) for x in totals]


def _pie_for_categories(
    categories: Sequence[ExpenseCategory | IncomeCategory],
    months: list[date],
    fact_map: dict[int, dict[date, Decimal]],
) -> tuple[list[str], list[float]]:
    labels: list[str] = []
    values: list[float] = []
    if not months or not categories:
        return labels, values
    totals: dict[int, Decimal] = defaultdict(lambda: Decimal(0))
    for cat in categories:
        for month in months:
            totals[cat.pk] += fact_map[cat.pk][month]
    for cat in categories:
        total = totals[cat.pk]
        if total > 0:
            labels.append(cat.name)
            values.append(float(total))
    return labels, values


def budget_charts(user: User) -> BudgetChartsDict:
    expense_dates = (
        Expense.objects.filter(user=user)
        .annotate(month=TruncMonth('date'))
        .values_list('month', flat=True)
        .distinct()
        .order_by('month')
    )
    income_dates = (
        Income.objects.filter(user=user)
        .annotate(month=TruncMonth('date'))
        .values_list('month', flat=True)
        .distinct()
        .order_by('month')
    )

    all_months_set = set()
    for d in expense_dates:
        if d:
            month_date = d.date() if hasattr(d, 'date') else d
            if isinstance(month_date, date):
                all_months_set.add(month_date)
    for d in income_dates:
        if d:
            month_date = d.date() if hasattr(d, 'date') else d
            if isinstance(month_date, date):
                all_months_set.add(month_date)

    months = sorted(all_months_set)

    expense_categories = list(
        user.category_expense_users.all().order_by('name'),
    )
    income_categories = list(
        user.category_income_users.all().order_by('name'),
    )

    chart_labels = [m.strftime('%b %Y') for m in months] if months else []

    expense_fact = _fact_map_for_categories(
        user,
        Expense,
        expense_categories,
        months,
    )
    income_fact = _fact_map_for_categories(
        user,
        Income,
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

    pie_labels, pie_values = _pie_for_categories(
        expense_categories,
        months,
        expense_fact,
    )

    return {
        'chart_labels': chart_labels,
        'chart_income': total_income,
        'chart_expense': total_expense,
        'chart_balance': chart_balance,
        'pie_labels': pie_labels,
        'pie_values': pie_values,
    }
