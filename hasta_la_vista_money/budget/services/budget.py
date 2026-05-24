"""Aggregation service used by the budget module.

After the income/expense merge this service depends on a single
``TransactionRepository`` and ``Category`` model from the
``transactions`` app, discriminating rows by ``type``.
"""

from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from django.db.models import QuerySet, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from typing_extensions import TypedDict

from hasta_la_vista_money.budget.repositories import PlanningRepository
from hasta_la_vista_money.transactions.models import Category, TransactionType
from hasta_la_vista_money.transactions.repositories import TransactionRepository
from hasta_la_vista_money.users.models import User


class ExpenseDataRowDict(TypedDict):
    """Expense data row."""

    category: str
    category_id: int
    fact: list[int]
    plan: list[int]
    diff: list[int]
    percent: list[float | None]


class IncomeDataRowDict(TypedDict):
    """Income data row."""

    category: str
    category_id: int
    fact: list[Decimal]
    plan: list[Decimal]
    diff: list[Decimal]
    percent: list[float | None]


class BudgetChartDataDict(TypedDict):
    """Budget chart data."""

    chart_labels: list[str]
    chart_plan_execution_income: list[float]
    chart_plan_execution_expense: list[float]
    chart_balance: list[float]


class AggregateBudgetDataDict(TypedDict):
    """Aggregated budget data."""

    months: list[date]
    expense_data: list[ExpenseDataRowDict]
    total_fact_expense: list[int]
    total_plan_expense: list[int]
    income_data: list[IncomeDataRowDict]
    total_fact_income: list[Decimal]
    total_plan_income: list[Decimal]
    chart_data: BudgetChartDataDict


class AggregateExpenseTableDict(TypedDict):
    """Aggregated expense table data."""

    months: list[date]
    expense_data: list[ExpenseDataRowDict]
    total_fact_expense: list[int]
    total_plan_expense: list[int]


class AggregateIncomeTableDict(TypedDict):
    """Aggregated income table data."""

    months: list[date]
    income_data: list[IncomeDataRowDict]
    total_fact_income: list[Decimal]
    total_plan_income: list[Decimal]


class AggregateExpenseApiDict(TypedDict):
    """Aggregated expense data for API."""

    months: list[str]
    data: list[dict[str, Any]]


class AggregateIncomeApiDict(TypedDict):
    """Aggregated income data for API."""

    months: list[str]
    data: list[dict[str, Any]]


class BudgetDataError(Exception):
    """Custom exception for budget data aggregation errors."""


def _month_range(months: list[date]) -> tuple[datetime, datetime]:
    """Return the inclusive datetime bounds covering a list of months."""
    start_date = timezone.make_aware(datetime.combine(months[0], time.min))
    end_date = timezone.make_aware(datetime.combine(months[-1], time.max))
    return start_date, end_date


class BudgetService:
    """Service for budget data aggregation."""

    def __init__(
        self,
        transaction_repository: TransactionRepository,
        planning_repository: PlanningRepository,
    ) -> None:
        self.transaction_repository = transaction_repository
        self.planning_repository = planning_repository

    def _get_fact_map_int(
        self,
        user: User,
        months: list[date],
        categories: list[Category],
        type_value: str,
    ) -> dict[int, dict[date, int]]:
        if not months:
            return {}

        start_date, end_date = _month_range(months)
        rows = (
            self.transaction_repository.filter(
                user=user,
                type=type_value,
                category__in=categories,
                date__gte=start_date,
                date__lte=end_date,
            )
            .annotate(month=TruncMonth('date'))
            .values('category_id', 'month')
            .annotate(total=Sum('amount'))
        )

        fact_map: dict[int, dict[date, int]] = defaultdict(
            lambda: defaultdict(lambda: 0),
        )
        for row in rows:
            month_date = (
                row['month'].date()
                if hasattr(row['month'], 'date')
                else row['month']
            )
            month_start = month_date.replace(day=1)
            fact_map[row['category_id']][month_start] = row['total'] or 0
        return fact_map

    def _get_fact_map_decimal(
        self,
        user: User,
        months: list[date],
        categories: list[Category],
        type_value: str,
    ) -> dict[int, dict[date, Decimal]]:
        if not months:
            return {}

        start_date, end_date = _month_range(months)
        rows = (
            self.transaction_repository.filter(
                user=user,
                type=type_value,
                category__in=categories,
                date__gte=start_date,
                date__lte=end_date,
            )
            .annotate(month=TruncMonth('date'))
            .values('category_id', 'month')
            .annotate(total=Sum('amount'))
        )

        fact_map: dict[int, dict[date, Decimal]] = defaultdict(
            lambda: defaultdict(lambda: Decimal(0)),
        )
        for row in rows:
            month_date = (
                row['month'].date()
                if hasattr(row['month'], 'date')
                else row['month']
            )
            month_start = month_date.replace(day=1)
            total = row['total']
            fact_map[row['category_id']][month_start] = (
                Decimal(str(total)) if total else Decimal(0)
            )
        return fact_map

    def _get_plan_map_int(
        self,
        user: User,
        months: list[date],
        categories: list[Category],
        type_value: str,
    ) -> dict[int, dict[date, int]]:
        plans = self.planning_repository.filter(
            user=user,
            date__in=months,
            planning_type=type_value,
            category__in=categories,
        ).values('category_id', 'date', 'amount')

        plan_map: dict[int, dict[date, int]] = defaultdict(
            lambda: defaultdict(lambda: 0),
        )
        for row in plans:
            amount = row['amount']
            plan_map[row['category_id']][row['date']] = int(amount or 0)
        return plan_map

    def _get_plan_map_decimal(
        self,
        user: User,
        months: list[date],
        categories: list[Category],
        type_value: str,
    ) -> dict[int, dict[date, Decimal]]:
        plans = self.planning_repository.filter(
            user=user,
            date__in=months,
            planning_type=type_value,
            category__in=categories,
        ).values('category_id', 'date', 'amount')

        plan_map: dict[int, dict[date, Decimal]] = defaultdict(
            lambda: defaultdict(lambda: Decimal(0)),
        )
        for row in plans:
            amount = row['amount']
            plan_map[row['category_id']][row['date']] = (
                Decimal(str(amount)) if amount else Decimal(0)
            )
        return plan_map

    def aggregate_budget_data(
        self,
        user: User,
        months: list[date],
        expense_categories: list[Category],
        income_categories: list[Category],
    ) -> AggregateBudgetDataDict:
        """Aggregate all budget data for the dashboard context."""
        _validate_budget_inputs(
            user,
            months,
            expense_categories,
            income_categories,
        )

        expense_fact_map = self._get_fact_map_int(
            user,
            months,
            expense_categories,
            TransactionType.EXPENSE,
        )
        expense_plan_map = self._get_plan_map_int(
            user,
            months,
            expense_categories,
            TransactionType.EXPENSE,
        )

        total_fact_expense, total_plan_expense = _calculate_expense_totals(
            expense_fact_map,
            expense_plan_map,
            months,
            expense_categories,
        )
        expense_data = _build_expense_data(
            expense_fact_map,
            expense_plan_map,
            months,
            expense_categories,
        )

        income_fact_map = self._get_fact_map_decimal(
            user,
            months,
            income_categories,
            TransactionType.INCOME,
        )
        income_plan_map = self._get_plan_map_decimal(
            user,
            months,
            income_categories,
            TransactionType.INCOME,
        )
        total_fact_income, total_plan_income = _calculate_income_totals(
            income_fact_map,
            income_plan_map,
            months,
            income_categories,
        )
        income_data = _build_income_data(
            income_fact_map,
            income_plan_map,
            months,
            income_categories,
        )

        chart_data = _build_chart_data(
            months,
            total_fact_income,
            total_plan_income,
            total_fact_expense,
            total_plan_expense,
        )

        return {
            'chart_data': chart_data,
            'months': months,
            'expense_data': expense_data,
            'income_data': income_data,
            'total_fact_expense': total_fact_expense,
            'total_plan_expense': total_plan_expense,
            'total_fact_income': total_fact_income,
            'total_plan_income': total_plan_income,
        }

    def aggregate_expense_table(
        self,
        user: User,
        months: list[date],
        expense_categories: list[Category],
    ) -> AggregateExpenseTableDict:
        """Aggregate data for the expense table view."""
        _validate_expense_table_inputs(user, months, expense_categories)

        expense_fact_map = self._get_fact_map_int(
            user,
            months,
            expense_categories,
            TransactionType.EXPENSE,
        )
        expense_plan_map = self._get_plan_map_int(
            user,
            months,
            expense_categories,
            TransactionType.EXPENSE,
        )

        expense_data, total_fact_expense, total_plan_expense = (
            _build_expense_table_data(
                expense_fact_map,
                expense_plan_map,
                months,
                expense_categories,
            )
        )

        return {
            'months': months,
            'expense_data': expense_data,
            'total_fact_expense': total_fact_expense,
            'total_plan_expense': total_plan_expense,
        }

    def aggregate_income_table(
        self,
        user: User,
        months: list[date],
        income_categories: list[Category],
    ) -> AggregateIncomeTableDict:
        """Aggregate data for the income table view."""
        _validate_income_table_inputs(user, months, income_categories)

        income_fact_map = self._get_fact_map_decimal(
            user,
            months,
            income_categories,
            TransactionType.INCOME,
        )
        income_plan_map = self._get_plan_map_decimal(
            user,
            months,
            income_categories,
            TransactionType.INCOME,
        )

        income_data, total_fact_income, total_plan_income = (
            _build_income_table_data(
                income_fact_map,
                income_plan_map,
                months,
                income_categories,
            )
        )

        return {
            'months': months,
            'income_data': income_data,
            'total_fact_income': total_fact_income,
            'total_plan_income': total_plan_income,
        }

    def aggregate_expense_api(
        self,
        user: User,
        months: list[date],
        expense_categories: list[Category],
    ) -> AggregateExpenseApiDict:
        """Aggregate data for the expense API endpoint."""
        _validate_expense_api_inputs(user, months, expense_categories)

        expense_fact_map = self._get_fact_map_int(
            user,
            months,
            expense_categories,
            TransactionType.EXPENSE,
        )
        expense_plan_map = self._get_plan_map_int(
            user,
            months,
            expense_categories,
            TransactionType.EXPENSE,
        )

        data = _build_expense_api_data(
            expense_fact_map,
            expense_plan_map,
            months,
            expense_categories,
        )
        return {'months': [m.isoformat() for m in months], 'data': data}

    def aggregate_income_api(
        self,
        user: User,
        months: list[date],
        income_categories: list[Category],
    ) -> AggregateIncomeApiDict:
        """Aggregate data for the income API endpoint."""
        _validate_income_api_inputs(user, months, income_categories)

        income_fact_map = self._get_fact_map_decimal(
            user,
            months,
            income_categories,
            TransactionType.INCOME,
        )
        income_plan_map = self._get_plan_map_decimal(
            user,
            months,
            income_categories,
            TransactionType.INCOME,
        )

        data = _build_income_api_data(
            income_fact_map,
            income_plan_map,
            months,
            income_categories,
        )
        return {'months': [m.isoformat() for m in months], 'data': data}


def get_categories(
    user: User | None,
    type_value: str,
) -> QuerySet[Category, Category]:
    """Return root categories for a user filtered by type."""
    if user is None:
        error_msg = 'User is required.'
        raise BudgetDataError(error_msg)
    return user.categories.filter(
        type=type_value,
        parent_category=None,
    ).order_by('name')


def _validate_budget_inputs(
    _user: User | None,
    months: list[date] | None,
    expense_categories: list[Category] | None,
    income_categories: list[Category] | None,
) -> None:
    if _user is None:
        raise BudgetDataError('User is required.')
    if months is None:
        raise BudgetDataError('Months list is required.')
    if expense_categories is None:
        raise BudgetDataError('Expense categories are required.')
    if income_categories is None:
        raise BudgetDataError('Income categories are required.')


def _calculate_expense_totals(
    expense_fact_map: dict[int, dict[date, int]],
    expense_plan_map: dict[int, dict[date, int]],
    months: list[date],
    expense_categories: list[Category],
) -> tuple[list[int], list[int]]:
    total_fact_expense = [0] * len(months)
    total_plan_expense = [0] * len(months)
    for i, m in enumerate(months):
        for cat in expense_categories:
            total_fact_expense[i] += expense_fact_map[cat.pk][m]
            total_plan_expense[i] += expense_plan_map[cat.pk][m]
    return total_fact_expense, total_plan_expense


def _build_expense_data(
    expense_fact_map: dict[int, dict[date, int]],
    expense_plan_map: dict[int, dict[date, int]],
    months: list[date],
    expense_categories: list[Category],
) -> list[ExpenseDataRowDict]:
    expense_data = []
    for cat in expense_categories:
        row: ExpenseDataRowDict = {
            'category': cat.name,
            'category_id': cat.pk,
            'fact': [],
            'plan': [],
            'diff': [],
            'percent': [],
        }
        for m in months:
            fact = expense_fact_map[cat.pk][m]
            plan = expense_plan_map[cat.pk][m]
            diff = fact - plan
            percent = (fact / plan * 100) if plan else None

            row['fact'].append(fact)
            row['plan'].append(plan)
            row['diff'].append(diff)
            row['percent'].append(
                float(percent) if percent is not None else None,
            )
        expense_data.append(row)
    return expense_data


def _calculate_income_totals(
    income_fact_map: dict[int, dict[date, Decimal]],
    income_plan_map: dict[int, dict[date, Decimal]],
    months: list[date],
    income_categories: list[Category],
) -> tuple[list[Decimal], list[Decimal]]:
    total_fact_income = [Decimal(0)] * len(months)
    total_plan_income = [Decimal(0)] * len(months)
    for i, m in enumerate(months):
        for cat in income_categories:
            total_fact_income[i] += income_fact_map[cat.pk][m]
            total_plan_income[i] += income_plan_map[cat.pk][m]
    return total_fact_income, total_plan_income


def _build_income_data(
    income_fact_map: dict[int, dict[date, Decimal]],
    income_plan_map: dict[int, dict[date, Decimal]],
    months: list[date],
    income_categories: list[Category],
) -> list[IncomeDataRowDict]:
    income_data = []
    for cat in income_categories:
        row: IncomeDataRowDict = {
            'category': cat.name,
            'category_id': cat.pk,
            'fact': [],
            'plan': [],
            'diff': [],
            'percent': [],
        }
        for m in months:
            fact = income_fact_map[cat.pk][m]
            plan = income_plan_map[cat.pk][m]
            diff = fact - plan
            percent = (fact / plan * 100) if plan else None

            row['fact'].append(fact)
            row['plan'].append(plan)
            row['diff'].append(diff)
            row['percent'].append(
                float(percent) if percent is not None else None,
            )
        income_data.append(row)
    return income_data


def _build_chart_data(
    months: list[date],
    total_fact_income: list[Decimal],
    total_plan_income: list[Decimal],
    total_fact_expense: list[int],
    total_plan_expense: list[int],
) -> BudgetChartDataDict:
    chart_labels = [m.strftime('%b %Y') for m in months]
    chart_plan_execution_income: list[float] = []
    chart_plan_execution_expense: list[float] = []
    chart_balance: list[float] = []

    for i in range(len(months)):
        income_percent = _calculate_percentage(
            total_fact_income[i],
            total_plan_income[i],
        )
        expense_percent = _calculate_percentage(
            total_fact_expense[i],
            total_plan_expense[i],
        )
        balance = float(total_fact_income[i]) - float(total_fact_expense[i])

        chart_plan_execution_income.append(float(income_percent))
        chart_plan_execution_expense.append(float(expense_percent))
        chart_balance.append(balance)

    return {
        'chart_labels': chart_labels,
        'chart_plan_execution_income': chart_plan_execution_income,
        'chart_plan_execution_expense': chart_plan_execution_expense,
        'chart_balance': chart_balance,
    }


def _calculate_percentage(fact: Decimal | int, plan: Decimal | int) -> Decimal:
    if plan > 0:
        fact_decimal = Decimal(fact) if isinstance(fact, int) else fact
        plan_decimal = Decimal(plan) if isinstance(plan, int) else plan
        return (fact_decimal / plan_decimal) * 100
    return Decimal(0) if fact == 0 else Decimal(100)


def _validate_expense_table_inputs(
    _user: User | None,
    months: list[date] | None,
    expense_categories: list[Category] | None,
) -> None:
    if _user is None:
        raise BudgetDataError('User is required.')
    if months is None:
        raise BudgetDataError('Months list is required.')
    if expense_categories is None:
        raise BudgetDataError('Expense categories are required.')


def _build_expense_table_data(
    expense_fact_map: dict[int, dict[date, int]],
    expense_plan_map: dict[int, dict[date, int]],
    months: list[date],
    expense_categories: list[Category],
) -> tuple[list[ExpenseDataRowDict], list[int], list[int]]:
    expense_data = []
    total_fact_expense = [0] * len(months)
    total_plan_expense = [0] * len(months)

    for cat in expense_categories:
        row: ExpenseDataRowDict = {
            'category': cat.name,
            'category_id': cat.pk,
            'fact': [],
            'plan': [],
            'diff': [],
            'percent': [],
        }
        for i, m in enumerate(months):
            fact = expense_fact_map[cat.pk][m]
            plan = expense_plan_map[cat.pk][m]
            diff = fact - plan
            percent = (fact / plan * 100) if plan else None

            row['fact'].append(fact)
            row['plan'].append(plan)
            row['diff'].append(diff)
            row['percent'].append(
                float(percent) if percent is not None else None,
            )
            total_fact_expense[i] += fact
            total_plan_expense[i] += plan
        expense_data.append(row)

    return expense_data, total_fact_expense, total_plan_expense


def _validate_income_table_inputs(
    _user: User | None,
    months: list[date] | None,
    income_categories: list[Category] | None,
) -> None:
    if _user is None:
        raise BudgetDataError('User is required.')
    if months is None:
        raise BudgetDataError('Months list is required.')
    if income_categories is None:
        raise BudgetDataError('Income categories are required.')


def _build_income_table_data(
    income_fact_map: dict[int, dict[date, Decimal]],
    income_plan_map: dict[int, dict[date, Decimal]],
    months: list[date],
    income_categories: list[Category],
) -> tuple[list[IncomeDataRowDict], list[Decimal], list[Decimal]]:
    income_data = []
    total_fact_income = [Decimal(0)] * len(months)
    total_plan_income = [Decimal(0)] * len(months)

    for cat in income_categories:
        row: IncomeDataRowDict = {
            'category': cat.name,
            'category_id': cat.pk,
            'fact': [],
            'plan': [],
            'diff': [],
            'percent': [],
        }
        for i, m in enumerate(months):
            fact = income_fact_map[cat.pk][m]
            plan = income_plan_map[cat.pk][m]
            diff = fact - plan
            percent = (fact / plan * 100) if plan else None

            row['fact'].append(fact)
            row['plan'].append(plan)
            row['diff'].append(diff)
            row['percent'].append(
                float(percent) if percent is not None else None,
            )
            total_fact_income[i] += fact
            total_plan_income[i] += plan
        income_data.append(row)

    return income_data, total_fact_income, total_plan_income


def _validate_expense_api_inputs(
    _user: User | None,
    months: list[date] | None,
    expense_categories: list[Category] | None,
) -> None:
    if _user is None:
        raise BudgetDataError('User is required.')
    if months is None:
        raise BudgetDataError('Months list is required.')
    if expense_categories is None:
        raise BudgetDataError('Expense categories are required.')


def _build_income_api_data(
    income_fact_map: dict[int, dict[date, Decimal]],
    income_plan_map: dict[int, dict[date, Decimal]],
    months: list[date],
    income_categories: list[Category],
) -> list[dict[str, Any]]:
    data = []
    for cat in income_categories:
        row: dict[str, Any] = {
            'category': cat.name,
            'category_id': cat.pk,
        }
        for m in months:
            month_str = m.isoformat()
            fact = income_fact_map[cat.pk][m]
            plan = income_plan_map[cat.pk][m]
            diff = fact - plan
            percent = (fact / plan * 100) if plan else None

            row[f'fact_{month_str}'] = float(fact)
            row[f'plan_{month_str}'] = float(plan)
            row[f'diff_{month_str}'] = float(diff)
            row[f'percent_{month_str}'] = (
                float(percent) if percent is not None else None
            )
        data.append(row)
    return data


def _build_expense_api_data(
    expense_fact_map: dict[int, dict[date, int]],
    expense_plan_map: dict[int, dict[date, int]],
    months: list[date],
    expense_categories: list[Category],
) -> list[dict[str, Any]]:
    data = []
    for cat in expense_categories:
        row: dict[str, Any] = {
            'category': cat.name,
            'category_id': cat.pk,
        }
        for m in months:
            month_str = m.isoformat()
            fact = expense_fact_map[cat.pk][m]
            plan = expense_plan_map[cat.pk][m]
            diff = fact - plan
            percent = (fact / plan * 100) if plan else None

            row[f'fact_{month_str}'] = fact
            row[f'plan_{month_str}'] = plan
            row[f'diff_{month_str}'] = diff
            row[f'percent_{month_str}'] = (
                float(percent) if percent is not None else None
            )
        data.append(row)
    return data


def _validate_income_api_inputs(
    _user: User | None,
    months: list[date] | None,
    income_categories: list[Category] | None,
) -> None:
    if _user is None:
        raise BudgetDataError('User is required.')
    if months is None:
        raise BudgetDataError('Months list is required.')
    if income_categories is None:
        raise BudgetDataError('Income categories are required.')
