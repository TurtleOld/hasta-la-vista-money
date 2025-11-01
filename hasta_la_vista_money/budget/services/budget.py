from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import QuerySet, Sum
from django.db.models.functions import TruncMonth
from typing_extensions import TypedDict

from hasta_la_vista_money.budget.models import Planning
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.users.models import User


class ExpenseDataRowDict(TypedDict):
    """Строка данных расхода."""

    category: str
    category_id: int
    fact: list[int]
    plan: list[int]
    diff: list[int]
    percent: list[float | None]


class IncomeDataRowDict(TypedDict):
    """Строка данных дохода."""

    category: str
    category_id: int
    fact: list[Decimal]
    plan: list[Decimal]
    diff: list[Decimal]
    percent: list[float | None]


class BudgetChartDataDict(TypedDict):
    """Данные для графика бюджета."""

    chart_labels: list[str]
    chart_plan_execution_income: list[float]
    chart_plan_execution_expense: list[float]
    chart_balance: list[float]


class AggregateBudgetDataDict(TypedDict):
    """Агрегированные данные бюджета."""

    months: list[date]
    expense_data: list[ExpenseDataRowDict]
    total_fact_expense: list[int]
    total_plan_expense: list[int]
    income_data: list[IncomeDataRowDict]
    total_fact_income: list[Decimal]
    total_plan_income: list[Decimal]
    chart_data: BudgetChartDataDict


class AggregateExpenseTableDict(TypedDict):
    """Данные для таблицы расходов."""

    months: list[date]
    expense_data: list[ExpenseDataRowDict]
    total_fact_expense: list[int]
    total_plan_expense: list[int]


class AggregateIncomeTableDict(TypedDict):
    """Данные для таблицы доходов."""

    months: list[date]
    income_data: list[IncomeDataRowDict]
    total_fact_income: list[Decimal]
    total_plan_income: list[Decimal]


class ExpenseApiDataRowDict(TypedDict):
    """Строка данных расхода для API."""

    category: str
    category_id: int
    months: list[str]
    fact: list[int]
    plan: list[int]
    diff: list[int]
    percent: list[float | None]


class IncomeApiDataRowDict(TypedDict):
    """Строка данных дохода для API."""

    category: str
    category_id: int
    months: list[str]
    fact: list[Decimal]
    plan: list[Decimal]
    diff: list[Decimal]
    percent: list[float | None]


class AggregateExpenseApiDict(TypedDict):
    """Данные расходов для API."""

    months: list[str]
    data: list[ExpenseApiDataRowDict]


class AggregateIncomeApiDict(TypedDict):
    """Данные доходов для API."""

    months: list[str]
    data: list[IncomeApiDataRowDict]


class BudgetDataError(Exception):
    """
    Custom exception for budget data aggregation errors.
    """


def get_categories(user: User, type_: str) -> QuerySet:
    """
    Returns queryset of categories for the user by type (expense/income).
    Raises BudgetDataError if user is None.
    """
    if not user:
        error_msg = 'User is required for category lookup.'
        raise BudgetDataError(error_msg)
    if type_ == 'expense':
        return user.category_expense_users.filter(
            parent_category=None,
        ).order_by('name')
    return user.category_income_users.filter(parent_category=None).order_by(
        'name',
    )


def _validate_budget_inputs(
    user: User,
    months: list[date],
    expense_categories: list[ExpenseCategory],
    income_categories: list[IncomeCategory],
) -> None:
    """Validate required inputs for budget aggregation."""
    if not user:
        error_msg = 'User is required for budget aggregation.'
        raise BudgetDataError(error_msg)
    if months is None:
        error_msg = 'Months list is required.'
        raise BudgetDataError(error_msg)
    if expense_categories is None or income_categories is None:
        error_msg = 'Expense and income categories are required.'
        raise BudgetDataError(error_msg)


def _get_expense_facts(
    user: User,
    months: list[date],
    expense_categories: list[ExpenseCategory],
) -> dict[int, dict[date, int]]:
    """Get expense facts data for given user and months."""
    if not months:
        return {}

    expenses = (
        Expense.objects.filter(
            user=user,
            category__in=expense_categories,
            date__gte=months[0],
            date__lte=months[-1],
        )
        .annotate(month=TruncMonth('date'))
        .values('category_id', 'month')
        .annotate(total=Sum('amount'))
    )

    expense_fact_map: dict[int, dict[date, int]] = defaultdict(
        lambda: defaultdict(lambda: 0),
    )

    for e in expenses:
        month_date = (
            e['month'].date() if hasattr(e['month'], 'date') else e['month']
        )
        month_start = month_date.replace(day=1)
        expense_fact_map[e['category_id']][month_start] = e['total'] or 0

    return expense_fact_map


def _get_expense_plans(
    user: User,
    months: list[date],
    expense_categories: list[ExpenseCategory],
) -> dict[int, dict[date, int]]:
    """Get expense plans data for given user and months."""
    plans_exp = Planning.objects.filter(
        user=user,
        date__in=months,
        type='expense',
        category_expense__in=expense_categories,
    ).values('category_expense_id', 'date', 'amount')

    expense_plan_map: dict[int, dict[date, int]] = defaultdict(
        lambda: defaultdict(lambda: 0),
    )

    for p in plans_exp:
        expense_plan_map[p['category_expense_id']][p['date']] = p['amount'] or 0

    return expense_plan_map


def _calculate_expense_totals(
    expense_fact_map: dict[int, dict[date, int]],
    expense_plan_map: dict[int, dict[date, int]],
    months: list[date],
    expense_categories: list[ExpenseCategory],
) -> tuple[list[int], list[int]]:
    """Calculate total fact and plan expenses for each month."""
    total_fact_expense = [0] * len(months)
    total_plan_expense = [0] * len(months)

    for i, m in enumerate(months):
        for cat in expense_categories:
            total_fact_expense[i] += expense_fact_map[cat.id][m]
            total_plan_expense[i] += expense_plan_map[cat.id][m]

    return total_fact_expense, total_plan_expense


def _build_expense_data(
    expense_fact_map: dict[int, dict[date, int]],
    expense_plan_map: dict[int, dict[date, int]],
    months: list[date],
    expense_categories: list[ExpenseCategory],
) -> list[ExpenseDataRowDict]:
    """Build expense data structure with fact, plan, diff, and percent."""
    expense_data = []

    for cat in expense_categories:
        row = {
            'category': cat.name,
            'category_id': cat.id,
            'fact': [],
            'plan': [],
            'diff': [],
            'percent': [],
        }

        for m in months:
            fact = expense_fact_map[cat.id][m]
            plan = expense_plan_map[cat.id][m]
            diff = fact - plan
            percent = (fact / plan * 100) if plan else None

            row['fact'].append(fact)
            row['plan'].append(plan)
            row['diff'].append(diff)
            row['percent'].append(percent)

        expense_data.append(row)

    return expense_data


def aggregate_budget_data(
    user: User,
    months: list[date],
    expense_categories: list[ExpenseCategory],
    income_categories: list[IncomeCategory],
) -> AggregateBudgetDataDict:
    """Aggregate all budget data for context."""
    _validate_budget_inputs(user, months, expense_categories, income_categories)

    expense_fact_map = _get_expense_facts(user, months, expense_categories)
    expense_plan_map = _get_expense_plans(user, months, expense_categories)

    total_fact_expense, total_plan_expense = _calculate_expense_totals(
        expense_fact_map, expense_plan_map, months, expense_categories
    )

    expense_data = _build_expense_data(
        expense_fact_map, expense_plan_map, months, expense_categories
    )

    income_fact_map = _get_income_facts(user, months, income_categories)
    income_plan_map = _get_income_plans(user, months, income_categories)

    total_fact_income, total_plan_income = _calculate_income_totals(
        income_fact_map, income_plan_map, months, income_categories
    )

    income_data = _build_income_data(
        income_fact_map, income_plan_map, months, income_categories
    )

    chart_data = _build_chart_data(
        months,
        total_fact_income,
        total_plan_income,
        total_fact_expense,
        total_plan_expense,
    )

    return {
        **chart_data,
        'months': months,
        'expense_data': expense_data,
        'income_data': income_data,
        'total_fact_expense': total_fact_expense,
        'total_plan_expense': total_plan_expense,
        'total_fact_income': total_fact_income,
        'total_plan_income': total_plan_income,
    }


def _get_income_facts(
    user: User,
    months: list[date],
    income_categories: list[IncomeCategory],
) -> dict[int, dict[date, Decimal]]:
    """Get income facts data for given user and months."""
    if not months:
        return {}

    income_queryset = (
        Income.objects.filter(
            user=user,
            category__in=income_categories,
            date__gte=months[0],
            date__lte=months[-1],
        )
        .annotate(month=TruncMonth('date'))
        .values('category_id', 'month')
        .annotate(total=Sum('amount'))
    )

    income_fact_map: dict[int, dict[date, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal(0)),
    )

    for e in income_queryset:
        month_date = (
            e['month'].date() if hasattr(e['month'], 'date') else e['month']
        )
        income_fact_map[e['category_id']][month_date] = e['total'] or Decimal(0)

    return income_fact_map


def _get_income_plans(
    user: User,
    months: list[date],
    income_categories: list[IncomeCategory],
) -> dict[int, dict[date, Decimal]]:
    """Get income plans data for given user and months."""
    plans_inc = Planning.objects.filter(
        user=user,
        date__in=months,
        type='income',
        category_income__in=income_categories,
    ).values('category_income_id', 'date', 'amount')

    income_plan_map = defaultdict(lambda: defaultdict(lambda: 0))

    for p in plans_inc:
        income_plan_map[p['category_income_id']][p['date']] = p[
            'amount'
        ] or Decimal(0)

    return income_plan_map


def _calculate_income_totals(
    income_fact_map: dict[int, dict[date, Decimal]],
    income_plan_map: dict[int, dict[date, Decimal]],
    months: list[date],
    income_categories: list[IncomeCategory],
) -> tuple[list[Decimal], list[Decimal]]:
    """Calculate total fact and plan incomes for each month."""
    total_fact_income = [Decimal(0)] * len(months)
    total_plan_income = [Decimal(0)] * len(months)

    for i, m in enumerate(months):
        for cat in income_categories:
            total_fact_income[i] += income_fact_map[cat.id][m]
            total_plan_income[i] += income_plan_map[cat.id][m]

    return total_fact_income, total_plan_income


def _build_income_data(
    income_fact_map: dict[int, dict[date, Decimal]],
    income_plan_map: dict[int, dict[date, Decimal]],
    months: list[date],
    income_categories: list[IncomeCategory],
) -> list[IncomeDataRowDict]:
    """Build income data structure with fact, plan, diff, and percent."""
    income_data = []

    for cat in income_categories:
        row = {
            'category': cat.name,
            'category_id': cat.id,
            'fact': [],
            'plan': [],
            'diff': [],
            'percent': [],
        }

        for m in months:
            fact = income_fact_map[cat.id][m]
            plan = income_plan_map[cat.id][m]
            diff = fact - plan
            percent = (fact / plan * 100) if plan else None

            row['fact'].append(fact)
            row['plan'].append(plan)
            row['diff'].append(diff)
            row['percent'].append(percent)

        income_data.append(row)

    return income_data


def _build_chart_data(
    months: list[date],
    total_fact_income: list[Decimal],
    total_plan_income: list[Decimal],
    total_fact_expense: list[int],
    total_plan_expense: list[int],
) -> BudgetChartDataDict:
    """Build chart data for budget visualization."""
    chart_labels = [m.strftime('%b %Y') for m in months]
    chart_plan_execution_income = []
    chart_plan_execution_expense = []

    for i in range(len(months)):
        income_percent = _calculate_percentage(
            total_fact_income[i], total_plan_income[i]
        )
        expense_percent = _calculate_percentage(
            total_fact_expense[i], total_plan_expense[i]
        )

        chart_plan_execution_income.append(float(income_percent))
        chart_plan_execution_expense.append(float(expense_percent))

    return {
        'chart_labels': chart_labels,
        'chart_plan_execution_income': chart_plan_execution_income,
        'chart_plan_execution_expense': chart_plan_execution_expense,
    }


def _calculate_percentage(fact: Decimal | int, plan: Decimal | int) -> Decimal:
    """Calculate percentage of fact vs plan."""
    if plan > 0:
        return (fact / plan) * 100
    return Decimal(0) if fact == 0 else Decimal(100)


def _validate_expense_table_inputs(
    user: User,
    months: list[date],
    expense_categories: list[ExpenseCategory],
) -> None:
    """Validate required inputs for expense table aggregation."""
    if not user:
        error_msg = 'User is required for expense table aggregation.'
        raise BudgetDataError(error_msg)
    if months is None:
        error_msg = 'Months list is required.'
        raise BudgetDataError(error_msg)
    if expense_categories is None:
        error_msg = 'Expense categories are required.'
        raise BudgetDataError(error_msg)


def _get_expense_table_facts(
    user: User,
    months: list[date],
    expense_categories: list[ExpenseCategory],
) -> dict[int, dict[date, int]]:
    """Get expense facts for table view."""
    if not months:
        return {}

    expenses = (
        Expense.objects.filter(
            user=user,
            category__in=expense_categories,
            date__gte=months[0],
            date__lte=months[-1],
        )
        .annotate(month=TruncMonth('date'))
        .values('category_id', 'month')
        .annotate(total=Sum('amount'))
    )

    expense_fact_map = defaultdict(lambda: defaultdict(lambda: 0))

    for e in expenses:
        month_date = (
            e['month'].date() if hasattr(e['month'], 'date') else e['month']
        )
        expense_fact_map[e['category_id']][month_date] = e['total'] or 0

    return expense_fact_map


def _get_expense_table_plans(
    user: User,
    months: list[date],
    expense_categories: list[ExpenseCategory],
) -> dict[int, dict[date, int]]:
    """Get expense plans for table view."""
    plans_expense = Planning.objects.filter(
        user=user,
        date__in=months,
        type='expense',
        category_expense__in=expense_categories,
    ).values('category_expense_id', 'date', 'amount')

    expense_plan_map = defaultdict(lambda: defaultdict(lambda: 0))

    for pln in plans_expense:
        expense_plan_map[pln['category_expense_id']][pln['date']] = (
            pln['amount'] or 0
        )

    return expense_plan_map


def _build_expense_table_data(
    expense_fact_map: dict[int, dict[date, int]],
    expense_plan_map: dict[int, dict[date, int]],
    months: list[date],
    expense_categories: list[ExpenseCategory],
) -> tuple[list[ExpenseDataRowDict], list[int], list[int]]:
    """Build expense table data structure."""
    expense_data = []
    total_fact_expense = [0] * len(months)
    total_plan_expense = [0] * len(months)

    for cat in expense_categories:
        row = {
            'category': cat.name,
            'category_id': cat.id,
            'fact': [],
            'plan': [],
            'diff': [],
            'percent': [],
        }

        for i, m in enumerate(months):
            fact = expense_fact_map[cat.id][m]
            plan = expense_plan_map[cat.id][m]
            diff = fact - plan
            percent = (fact / plan * 100) if plan else None

            row['fact'].append(fact)
            row['plan'].append(plan)
            row['diff'].append(diff)
            row['percent'].append(percent)
            total_fact_expense[i] += fact
            total_plan_expense[i] += plan

        expense_data.append(row)

    return expense_data, total_fact_expense, total_plan_expense


def aggregate_expense_table(
    user: User,
    months: list[date],
    expense_categories: list[ExpenseCategory],
) -> AggregateExpenseTableDict:
    """Aggregate data for the expense table view."""
    _validate_expense_table_inputs(user, months, expense_categories)

    expense_fact_map = _get_expense_table_facts(
        user, months, expense_categories
    )
    expense_plan_map = _get_expense_table_plans(
        user, months, expense_categories
    )

    expense_data, total_fact_expense, total_plan_expense = (
        _build_expense_table_data(
            expense_fact_map, expense_plan_map, months, expense_categories
        )
    )

    return {
        'months': months,
        'expense_data': expense_data,
        'total_fact_expense': total_fact_expense,
        'total_plan_expense': total_plan_expense,
    }


def _validate_income_table_inputs(
    user: User,
    months: list[date],
    income_categories: list[IncomeCategory],
) -> None:
    """Validate required inputs for income table aggregation."""
    if not user:
        error_msg = 'User is required for income table aggregation.'
        raise BudgetDataError(error_msg)
    if months is None:
        error_msg = 'Months list is required.'
        raise BudgetDataError(error_msg)
    if income_categories is None:
        error_msg = 'Income categories are required.'
        raise BudgetDataError(error_msg)


def _get_income_table_facts(
    user: User,
    months: list[date],
    income_categories: list[IncomeCategory],
) -> dict[int, dict[date, Decimal]]:
    """Get income facts for table view."""
    if not months:
        return {}

    income_queryset = (
        Income.objects.filter(
            user=user,
            category__in=income_categories,
            date__gte=months[0],
            date__lte=months[-1],
        )
        .annotate(month=TruncMonth('date'))
        .values('category_id', 'month')
        .annotate(total=Sum('amount'))
    )

    income_fact_map = defaultdict(lambda: defaultdict(lambda: Decimal(0)))

    for e in income_queryset:
        month_date = (
            e['month'].date() if hasattr(e['month'], 'date') else e['month']
        )
        income_fact_map[e['category_id']][month_date] = e['total'] or Decimal(0)

    return income_fact_map


def _get_income_table_plans(
    user: User,
    months: list[date],
    income_categories: list[IncomeCategory],
) -> dict[int, dict[date, Decimal]]:
    """Get income plans for table view."""
    plans_inc = Planning.objects.filter(
        user=user,
        date__in=months,
        type='income',
        category_income__in=income_categories,
    ).values('category_income_id', 'date', 'amount')

    income_plan_map = defaultdict(lambda: defaultdict(lambda: Decimal(0)))

    for p in plans_inc:
        income_plan_map[p['category_income_id']][p['date']] = p[
            'amount'
        ] or Decimal(0)

    return income_plan_map


def _build_income_table_data(
    income_fact_map: dict[int, dict[date, Decimal]],
    income_plan_map: dict[int, dict[date, Decimal]],
    months: list[date],
    income_categories: list[IncomeCategory],
) -> tuple[list[IncomeDataRowDict], list[Decimal], list[Decimal]]:
    """Build income table data structure."""
    income_data = []
    total_fact_income = [Decimal(0)] * len(months)
    total_plan_income = [Decimal(0)] * len(months)

    for cat in income_categories:
        row = {
            'category': cat.name,
            'category_id': cat.id,
            'fact': [],
            'plan': [],
            'diff': [],
            'percent': [],
        }

        for i, m in enumerate(months):
            fact = income_fact_map[cat.id][m]
            plan = income_plan_map[cat.id][m]
            diff = fact - plan
            percent = (fact / plan * 100) if plan else None

            row['fact'].append(fact)
            row['plan'].append(plan)
            row['diff'].append(diff)
            row['percent'].append(percent)
            total_fact_income[i] += fact
            total_plan_income[i] += plan

        income_data.append(row)

    return income_data, total_fact_income, total_plan_income


def aggregate_income_table(
    user: User,
    months: list[date],
    income_categories: list[IncomeCategory],
) -> AggregateIncomeTableDict:
    """Aggregate data for the income table view."""
    _validate_income_table_inputs(user, months, income_categories)

    income_fact_map = _get_income_table_facts(user, months, income_categories)
    income_plan_map = _get_income_table_plans(user, months, income_categories)

    income_data, total_fact_income, total_plan_income = (
        _build_income_table_data(
            income_fact_map, income_plan_map, months, income_categories
        )
    )

    return {
        'months': months,
        'income_data': income_data,
        'total_fact_income': total_fact_income,
        'total_plan_income': total_plan_income,
    }


def _validate_expense_api_inputs(
    user: User,
    months: list[date],
    expense_categories: list[ExpenseCategory],
) -> None:
    """Validate required inputs for expense API aggregation."""
    if not user:
        error_msg = 'User is required for expense API aggregation.'
        raise BudgetDataError(error_msg)
    if months is None:
        error_msg = 'Months list is required.'
        raise BudgetDataError(error_msg)
    if expense_categories is None:
        error_msg = 'Expense categories are required.'
        raise BudgetDataError(error_msg)


def _get_expense_api_facts(
    user: User,
    months: list[date],
    expense_categories: list[ExpenseCategory],
) -> dict[int, dict[date, int]]:
    """Get expense facts for API view."""
    if not months:
        return {}

    expenses = (
        Expense.objects.filter(
            user=user,
            category__in=expense_categories,
            date__gte=months[0],
            date__lte=months[-1],
        )
        .annotate(month=TruncMonth('date'))
        .values('category_id', 'month')
        .annotate(total=Sum('amount'))
    )

    expense_fact_map = defaultdict(lambda: defaultdict(lambda: 0))

    for e in expenses:
        month_date = (
            e['month'].date() if hasattr(e['month'], 'date') else e['month']
        )
        month_start = month_date.replace(day=1)
        expense_fact_map[e['category_id']][month_start] = e['total'] or 0

    return expense_fact_map


def _get_expense_api_plans(
    user: User,
    months: list[date],
    expense_categories: list[ExpenseCategory],
) -> dict[int, dict[date, int]]:
    """Get expense plans for API view."""
    plans_expense = Planning.objects.filter(
        user=user,
        date__in=months,
        type='expense',
        category_expense__in=expense_categories,
    ).values('category_expense_id', 'date', 'amount')

    expense_plan_map = defaultdict(lambda: defaultdict(lambda: 0))

    for pln in plans_expense:
        expense_plan_map[pln['category_expense_id']][pln['date']] = (
            pln['amount'] or 0
        )

    return expense_plan_map


def _build_expense_api_data(
    expense_fact_map: dict[int, dict[date, int]],
    expense_plan_map: dict[int, dict[date, int]],
    months: list[date],
    expense_categories: list[ExpenseCategory],
) -> list[ExpenseApiDataRowDict]:
    """Build expense API data structure."""
    data = []

    for cat in expense_categories:
        row = {
            'category': cat.name,
            'category_id': cat.id,
        }

        for m in months:
            fact = expense_fact_map[cat.id][m]
            plan = expense_plan_map[cat.id][m]
            diff = fact - plan
            percent = (fact / plan * 100) if plan else None

            row[f'fact_{m}'] = float(fact) if fact is not None else None
            row[f'plan_{m}'] = float(plan) if plan is not None else None
            row[f'diff_{m}'] = float(diff) if diff is not None else None
            row[f'percent_{m}'] = (
                float(percent) if percent is not None else None
            )

        data.append(row)

    return data


def aggregate_expense_api(
    user: User,
    months: list[date],
    expense_categories: list[ExpenseCategory],
) -> AggregateExpenseApiDict:
    """Aggregate data for the expense API view."""
    _validate_expense_api_inputs(user, months, expense_categories)

    expense_fact_map = _get_expense_api_facts(user, months, expense_categories)
    expense_plan_map = _get_expense_api_plans(user, months, expense_categories)

    data = _build_expense_api_data(
        expense_fact_map, expense_plan_map, months, expense_categories
    )

    return {'months': [m.isoformat() for m in months], 'data': data}


def _validate_income_api_inputs(
    user: User,
    months: list[date],
    income_categories: list[IncomeCategory],
) -> None:
    """Validate required inputs for income API aggregation."""
    if not user:
        error_msg = 'User is required for income API aggregation.'
        raise BudgetDataError(error_msg)
    if months is None:
        error_msg = 'Months list is required.'
        raise BudgetDataError(error_msg)
    if income_categories is None:
        error_msg = 'Income categories are required.'
        raise BudgetDataError(error_msg)


def _get_income_api_facts(
    user: User,
    months: list[date],
    income_categories: list[IncomeCategory],
) -> dict[int, dict[date, int]]:
    """Get income facts for API view."""
    if not months:
        return {}

    incomes = (
        Income.objects.filter(
            user=user,
            category__in=income_categories,
            date__gte=months[0],
            date__lte=months[-1],
        )
        .annotate(month=TruncMonth('date'))
        .values('category_id', 'month')
        .annotate(total=Sum('amount'))
    )

    income_fact_map = defaultdict(lambda: defaultdict(lambda: 0))

    for e in incomes:
        month_date = (
            e['month'].date() if hasattr(e['month'], 'date') else e['month']
        )
        month_start = month_date.replace(day=1)
        income_fact_map[e['category_id']][month_start] = e['total'] or 0

    return income_fact_map


def _get_income_api_plans(
    user: User,
    months: list[date],
    income_categories: list[IncomeCategory],
) -> dict[int, dict[date, int]]:
    """Get income plans for API view."""
    plans_income = Planning.objects.filter(
        user=user,
        date__in=months,
        type='income',
        category_income__in=income_categories,
    ).values('category_income_id', 'date', 'amount')

    income_plan_map = defaultdict(lambda: defaultdict(lambda: 0))

    for pln in plans_income:
        income_plan_map[pln['category_income_id']][pln['date']] = (
            pln['amount'] or 0
        )

    return income_plan_map


def _build_income_api_data(
    income_fact_map: dict[int, dict[date, int]],
    income_plan_map: dict[int, dict[date, int]],
    months: list[date],
    income_categories: list[IncomeCategory],
) -> list[IncomeApiDataRowDict]:
    """Build income API data structure."""
    data = []

    for cat in income_categories:
        row = {
            'category': cat.name,
            'category_id': cat.id,
        }

        for m in months:
            fact = income_fact_map[cat.id][m]
            plan = income_plan_map[cat.id][m]
            diff = fact - plan
            percent = (fact / plan * 100) if plan else None

            row[f'fact_{m}'] = float(fact) if fact is not None else None
            row[f'plan_{m}'] = float(plan) if plan is not None else None
            row[f'diff_{m}'] = float(diff) if diff is not None else None
            row[f'percent_{m}'] = (
                float(percent) if percent is not None else None
            )

        data.append(row)

    return data


def aggregate_income_api(
    user: User,
    months: list[date],
    income_categories: list[IncomeCategory],
) -> AggregateIncomeApiDict:
    """Aggregate data for the income API view."""
    _validate_income_api_inputs(user, months, income_categories)

    income_fact_map = _get_income_api_facts(user, months, income_categories)
    income_plan_map = _get_income_api_plans(user, months, income_categories)

    data = _build_income_api_data(
        income_fact_map, income_plan_map, months, income_categories
    )

    return {'months': [m.isoformat() for m in months], 'data': data}
