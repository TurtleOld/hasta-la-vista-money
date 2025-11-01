from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import Model, Sum
from django.db.models.functions import TruncMonth
from typing_extensions import TypedDict

from hasta_la_vista_money.budget.models import DateList
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
            if expense.category and expense.category.parent_category
            else (
                expense.category.name if expense.category else 'Без категории'
            )
        )
        month = expense.date.strftime('%B %Y')
        amount = float(expense.amount or 0)
        expense_data[parent_category_name][month] += amount

        if expense.category and expense.category.parent_category:
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
    model: type[Model],
    categories: Sequence[ExpenseCategory | IncomeCategory],
    months: list[date],
) -> dict[int, dict[date, Decimal]]:
    fact_map: dict[int, dict[date, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal(0)),
    )
    if not months:
        return fact_map
    qs = (
        model.objects.filter(
            user=user,
            category__in=categories,
            date__gte=months[0],
            date__lte=months[-1],
        )
        .annotate(month=TruncMonth('date'))
        .values('category_id', 'month')
        .annotate(total=Sum('amount'))
    )
    for row in qs:
        month_date = (
            row['month'].date()
            if hasattr(row['month'], 'date')
            else row['month']
        )
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
            totals[i] += fact_map[cat.id][m]  # type: ignore[union-attr]
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
            totals[cat.id] += fact_map[cat.id][month]  # type: ignore[union-attr]
    for cat in categories:
        total = totals[cat.id]  # type: ignore[union-attr]
        if total > 0:
            labels.append(cat.name)
            values.append(float(total))
    return labels, values


def budget_charts(user: User) -> BudgetChartsDict:
    list_dates = DateList.objects.filter(user=user).order_by('date')
    months = [d.date for d in list_dates]

    expense_categories = list(
        user.category_expense_users.filter(parent_category=None).order_by(  # type: ignore[attr-defined]
            'name',
        ),
    )
    income_categories = list(
        user.category_income_users.filter(parent_category=None).order_by(
            'name',
        ),  # type: ignore[attr-defined]
    )

    chart_labels = [m.strftime('%b %Y') for m in months]

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

    chart_balance = [
        total_income[i] - total_expense[i] for i in range(len(months))
    ]

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
