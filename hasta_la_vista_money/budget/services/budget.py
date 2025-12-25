from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import QuerySet, Sum
from django.db.models.functions import TruncMonth
from typing_extensions import TypedDict

from hasta_la_vista_money.budget.repositories import PlanningRepository
from hasta_la_vista_money.expense.models import ExpenseCategory
from hasta_la_vista_money.expense.repositories import ExpenseRepository
from hasta_la_vista_money.income.models import IncomeCategory
from hasta_la_vista_money.income.repositories import IncomeRepository
from hasta_la_vista_money.users.models import User


class ExpenseDataRowDict(TypedDict):
    """Expense data row.

    Attributes:
        category: Category name.
        category_id: Category ID.
        fact: List of actual expense amounts per month.
        plan: List of planned expense amounts per month.
        diff: List of differences (fact - plan) per month.
        percent: List of percentages (fact/plan * 100) per month.
    """

    category: str
    category_id: int
    fact: list[int]
    plan: list[int]
    diff: list[int]
    percent: list[float | None]


class IncomeDataRowDict(TypedDict):
    """Income data row.

    Attributes:
        category: Category name.
        category_id: Category ID.
        fact: List of actual income amounts per month.
        plan: List of planned income amounts per month.
        diff: List of differences (fact - plan) per month.
        percent: List of percentages (fact/plan * 100) per month.
    """

    category: str
    category_id: int
    fact: list[Decimal]
    plan: list[Decimal]
    diff: list[Decimal]
    percent: list[float | None]


class BudgetChartDataDict(TypedDict):
    """Budget chart data.

    Attributes:
        chart_labels: List of month labels for chart.
        chart_plan_execution_income: List of income plan execution
            percentages.
        chart_plan_execution_expense: List of expense plan execution
            percentages.
        chart_balance: List of balance amounts per month.
    """

    chart_labels: list[str]
    chart_plan_execution_income: list[float]
    chart_plan_execution_expense: list[float]
    chart_balance: list[float]


class AggregateBudgetDataDict(TypedDict):
    """Aggregated budget data.

    Attributes:
        months: List of months in the period.
        expense_data: List of expense data rows.
        total_fact_expense: List of total actual expenses per month.
        total_plan_expense: List of total planned expenses per month.
        income_data: List of income data rows.
        total_fact_income: List of total actual income per month.
        total_plan_income: List of total planned income per month.
        chart_data: Chart visualization data.
    """

    months: list[date]
    expense_data: list[ExpenseDataRowDict]
    total_fact_expense: list[int]
    total_plan_expense: list[int]
    income_data: list[IncomeDataRowDict]
    total_fact_income: list[Decimal]
    total_plan_income: list[Decimal]
    chart_data: BudgetChartDataDict


class AggregateExpenseTableDict(TypedDict):
    """Aggregated expense table data.

    Attributes:
        months: List of months in the period.
        expense_data: List of expense data rows.
        total_fact_expense: List of total actual expenses per month.
        total_plan_expense: List of total planned expenses per month.
    """

    months: list[date]
    expense_data: list[ExpenseDataRowDict]
    total_fact_expense: list[int]
    total_plan_expense: list[int]


class AggregateIncomeTableDict(TypedDict):
    """Aggregated income table data.

    Attributes:
        months: List of months in the period.
        income_data: List of income data rows.
        total_fact_income: List of total actual income per month.
        total_plan_income: List of total planned income per month.
    """

    months: list[date]
    income_data: list[IncomeDataRowDict]
    total_fact_income: list[Decimal]
    total_plan_income: list[Decimal]


class ExpenseApiDataRowDict(TypedDict, total=False):
    """Expense data row for API.

    Attributes:
        category: Category name.
        category_id: Category ID.
    """

    category: str
    category_id: int


class IncomeApiDataRowDict(TypedDict, total=False):
    """Income data row for API.

    Attributes:
        category: Category name.
        category_id: Category ID.
    """

    category: str
    category_id: int


class AggregateExpenseApiDict(TypedDict):
    """Aggregated expense data for API.

    Attributes:
        months: List of month strings in ISO format.
        data: List of expense data dictionaries.
    """

    months: list[str]
    data: list[dict[str, Any]]


class AggregateIncomeApiDict(TypedDict):
    """Aggregated income data for API.

    Attributes:
        months: List of month strings in ISO format.
        data: List of income data dictionaries.
    """

    months: list[str]
    data: list[dict[str, Any]]


class BudgetDataError(Exception):
    """Custom exception for budget data aggregation errors."""


class BudgetService:
    """Service for budget data aggregation.

    Handles aggregation of budget data including expenses, income, plans,
    and facts for various views (table, chart, API).
    """

    def __init__(
        self,
        expense_repository: ExpenseRepository,
        income_repository: IncomeRepository,
        planning_repository: PlanningRepository,
    ) -> None:
        """Initialize BudgetService.

        Args:
            expense_repository: Repository for expense data access.
            income_repository: Repository for income data access.
            planning_repository: Repository for planning data access.
        """
        self.expense_repository = expense_repository
        self.income_repository = income_repository
        self.planning_repository = planning_repository

    def _get_expense_facts(
        self,
        user: User,
        months: list[date],
        expense_categories: list[ExpenseCategory],
    ) -> dict[int, dict[date, int]]:
        """Get expense facts data for given user and months.

        Args:
            user: User to get expenses for.
            months: List of months to aggregate.
            expense_categories: List of expense categories to filter.

        Returns:
            Dictionary mapping category_id to month->amount mapping.
        """
        if not months:
            return {}

        expenses = (
            self.expense_repository.filter(
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
        self,
        user: User,
        months: list[date],
        expense_categories: list[ExpenseCategory],
    ) -> dict[int, dict[date, int]]:
        """Get expense plans data for given user and months.

        Args:
            user: User to get plans for.
            months: List of months to aggregate.
            expense_categories: List of expense categories to filter.

        Returns:
            Dictionary mapping category_id to month->amount mapping.
        """
        plans_exp = self.planning_repository.filter(
            user=user,
            date__in=months,
            planning_type='expense',
            category_expense__in=expense_categories,
        ).values('category_expense_id', 'date', 'amount')

        expense_plan_map: dict[int, dict[date, int]] = defaultdict(
            lambda: defaultdict(lambda: 0),
        )

        for p in plans_exp:
            amount = p['amount']
            expense_plan_map[p['category_expense_id']][p['date']] = int(
                amount or 0,
            )

        return expense_plan_map

    def _get_income_facts(
        self,
        user: User,
        months: list[date],
        income_categories: list[IncomeCategory],
    ) -> dict[int, dict[date, Decimal]]:
        """Get income facts data for given user and months.

        Args:
            user: User to get income for.
            months: List of months to aggregate.
            income_categories: List of income categories to filter.

        Returns:
            Dictionary mapping category_id to month->amount mapping.
        """
        if not months:
            return {}

        income_queryset = (
            self.income_repository.filter(
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
            income_fact_map[e['category_id']][month_date] = e[
                'total'
            ] or Decimal(0)

        return income_fact_map

    def _get_income_plans(
        self,
        user: User,
        months: list[date],
        income_categories: list[IncomeCategory],
    ) -> dict[int, dict[date, Decimal]]:
        """Get income plans data for given user and months.

        Args:
            user: User to get plans for.
            months: List of months to aggregate.
            income_categories: List of income categories to filter.

        Returns:
            Dictionary mapping category_id to month->amount mapping.
        """
        plans_inc = self.planning_repository.filter(
            user=user,
            date__in=months,
            planning_type='income',
            category_income__in=income_categories,
        ).values('category_income_id', 'date', 'amount')

        income_plan_map: dict[int, dict[date, Decimal]] = defaultdict(
            lambda: defaultdict(lambda: Decimal(0)),
        )

        for p in plans_inc:
            income_plan_map[p['category_income_id']][p['date']] = p[
                'amount'
            ] or Decimal(0)

        return income_plan_map

    def aggregate_budget_data(
        self,
        user: User,
        months: list[date],
        expense_categories: list[ExpenseCategory],
        income_categories: list[IncomeCategory],
    ) -> AggregateBudgetDataDict:
        """Aggregate all budget data for context.

        Args:
            user: User to aggregate data for.
            months: List of months to aggregate.
            expense_categories: List of expense categories.
            income_categories: List of income categories.

        Returns:
            AggregateBudgetDataDict with all aggregated budget data.

        Raises:
            BudgetDataError: If validation fails.
        """
        _validate_budget_inputs(
            user,
            months,
            expense_categories,
            income_categories,
        )

        expense_fact_map = self._get_expense_facts(
            user,
            months,
            expense_categories,
        )
        expense_plan_map = self._get_expense_plans(
            user,
            months,
            expense_categories,
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

        income_fact_map = self._get_income_facts(
            user,
            months,
            income_categories,
        )
        income_plan_map = self._get_income_plans(
            user,
            months,
            income_categories,
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

    def _get_expense_table_facts(
        self,
        user: User,
        months: list[date],
        expense_categories: list[ExpenseCategory],
    ) -> dict[int, dict[date, int]]:
        """Get expense facts for table view.

        Args:
            user: User to get expenses for.
            months: List of months to aggregate.
            expense_categories: List of expense categories to filter.

        Returns:
            Dictionary mapping category_id to month->amount mapping.
        """
        if not months:
            return {}

        expenses = (
            self.expense_repository.filter(
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
            expense_fact_map[e['category_id']][month_date] = e['total'] or 0

        return expense_fact_map

    def _get_expense_table_plans(
        self,
        user: User,
        months: list[date],
        expense_categories: list[ExpenseCategory],
    ) -> dict[int, dict[date, int]]:
        """Get expense plans for table view.

        Args:
            user: User to get plans for.
            months: List of months to aggregate.
            expense_categories: List of expense categories to filter.

        Returns:
            Dictionary mapping category_id to month->amount mapping.
        """
        plans_expense = self.planning_repository.filter(
            user=user,
            date__in=months,
            planning_type='expense',
            category_expense__in=expense_categories,
        ).values('category_expense_id', 'date', 'amount')

        expense_plan_map: dict[int, dict[date, int]] = defaultdict(
            lambda: defaultdict(lambda: 0),
        )

        for pln in plans_expense:
            amount = pln['amount']
            expense_plan_map[pln['category_expense_id']][pln['date']] = int(
                amount or 0,
            )

        return expense_plan_map

    def aggregate_expense_table(
        self,
        user: User,
        months: list[date],
        expense_categories: list[ExpenseCategory],
    ) -> AggregateExpenseTableDict:
        """Aggregate data for the expense table view.

        Args:
            user: User to aggregate data for.
            months: List of months to aggregate.
            expense_categories: List of expense categories.

        Returns:
            AggregateExpenseTableDict with expense table data.

        Raises:
            BudgetDataError: If validation fails.
        """
        _validate_expense_table_inputs(user, months, expense_categories)

        expense_fact_map = self._get_expense_table_facts(
            user,
            months,
            expense_categories,
        )
        expense_plan_map = self._get_expense_table_plans(
            user,
            months,
            expense_categories,
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

    def _get_income_table_facts(
        self,
        user: User,
        months: list[date],
        income_categories: list[IncomeCategory],
    ) -> dict[int, dict[date, Decimal]]:
        """Get income facts for table view.

        Args:
            user: User to get income for.
            months: List of months to aggregate.
            income_categories: List of income categories to filter.

        Returns:
            Dictionary mapping category_id to month->amount mapping.
        """
        if not months:
            return {}

        income_queryset = (
            self.income_repository.filter(
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
            income_fact_map[e['category_id']][month_date] = e[
                'total'
            ] or Decimal(0)

        return income_fact_map

    def _get_income_table_plans(
        self,
        user: User,
        months: list[date],
        income_categories: list[IncomeCategory],
    ) -> dict[int, dict[date, Decimal]]:
        """Get income plans for table view.

        Args:
            user: User to get plans for.
            months: List of months to aggregate.
            income_categories: List of income categories to filter.

        Returns:
            Dictionary mapping category_id to month->amount mapping.
        """
        plans_inc = self.planning_repository.filter(
            user=user,
            date__in=months,
            planning_type='income',
            category_income__in=income_categories,
        ).values('category_income_id', 'date', 'amount')

        income_plan_map: dict[int, dict[date, Decimal]] = defaultdict(
            lambda: defaultdict(lambda: Decimal(0)),
        )

        for p in plans_inc:
            income_plan_map[p['category_income_id']][p['date']] = p[
                'amount'
            ] or Decimal(0)

        return income_plan_map

    def aggregate_income_table(
        self,
        user: User,
        months: list[date],
        income_categories: list[IncomeCategory],
    ) -> AggregateIncomeTableDict:
        """Aggregate data for the income table view.

        Args:
            user: User to aggregate data for.
            months: List of months to aggregate.
            income_categories: List of income categories.

        Returns:
            AggregateIncomeTableDict with income table data.

        Raises:
            BudgetDataError: If validation fails.
        """
        _validate_income_table_inputs(user, months, income_categories)

        income_fact_map = self._get_income_table_facts(
            user,
            months,
            income_categories,
        )
        income_plan_map = self._get_income_table_plans(
            user,
            months,
            income_categories,
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

    def _get_expense_api_facts(
        self,
        user: User,
        months: list[date],
        expense_categories: list[ExpenseCategory],
    ) -> dict[int, dict[date, int]]:
        """Get expense facts for API view.

        Args:
            user: User to get expenses for.
            months: List of months to aggregate.
            expense_categories: List of expense categories to filter.

        Returns:
            Dictionary mapping category_id to month->amount mapping.
        """
        if not months:
            return {}

        expenses = (
            self.expense_repository.filter(
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

    def _get_expense_api_plans(
        self,
        user: User,
        months: list[date],
        expense_categories: list[ExpenseCategory],
    ) -> dict[int, dict[date, int]]:
        """Get expense plans for API view.

        Args:
            user: User to get plans for.
            months: List of months to aggregate.
            expense_categories: List of expense categories to filter.

        Returns:
            Dictionary mapping category_id to month->amount mapping.
        """
        plans_expense = self.planning_repository.filter(
            user=user,
            date__in=months,
            planning_type='expense',
            category_expense__in=expense_categories,
        ).values('category_expense_id', 'date', 'amount')

        expense_plan_map: dict[int, dict[date, int]] = defaultdict(
            lambda: defaultdict(lambda: 0),
        )

        for pln in plans_expense:
            amount = pln['amount']
            expense_plan_map[pln['category_expense_id']][pln['date']] = int(
                amount or 0,
            )

        return expense_plan_map

    def aggregate_expense_api(
        self,
        user: User,
        months: list[date],
        expense_categories: list[ExpenseCategory],
    ) -> AggregateExpenseApiDict:
        """Aggregate data for the expense API view.

        Args:
            user: User to aggregate data for.
            months: List of months to aggregate.
            expense_categories: List of expense categories.

        Returns:
            AggregateExpenseApiDict with expense API data.

        Raises:
            BudgetDataError: If validation fails.
        """
        _validate_expense_api_inputs(user, months, expense_categories)

        expense_fact_map = self._get_expense_api_facts(
            user,
            months,
            expense_categories,
        )
        expense_plan_map = self._get_expense_api_plans(
            user,
            months,
            expense_categories,
        )

        data = _build_expense_api_data(
            expense_fact_map,
            expense_plan_map,
            months,
            expense_categories,
        )

        return {'months': [m.isoformat() for m in months], 'data': data}

    def _get_income_api_facts(
        self,
        user: User,
        months: list[date],
        income_categories: list[IncomeCategory],
    ) -> dict[int, dict[date, Decimal]]:
        """Get income facts for API view.

        Args:
            user: User to get income for.
            months: List of months to aggregate.
            income_categories: List of income categories to filter.

        Returns:
            Dictionary mapping category_id to month->amount mapping.
        """
        if not months:
            return {}

        incomes = (
            self.income_repository.filter(
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

        for e in incomes:
            month_date = (
                e['month'].date() if hasattr(e['month'], 'date') else e['month']
            )
            month_start = month_date.replace(day=1)
            total = e['total']
            income_fact_map[e['category_id']][month_start] = (
                Decimal(str(total)) if total else Decimal(0)
            )

        return income_fact_map

    def _get_income_api_plans(
        self,
        user: User,
        months: list[date],
        income_categories: list[IncomeCategory],
    ) -> dict[int, dict[date, Decimal]]:
        """Get income plans for API view.

        Args:
            user: User to get plans for.
            months: List of months to aggregate.
            income_categories: List of income categories to filter.

        Returns:
            Dictionary mapping category_id to month->amount mapping.
        """
        plans_income = self.planning_repository.filter(
            user=user,
            date__in=months,
            planning_type='income',
            category_income__in=income_categories,
        ).values('category_income_id', 'date', 'amount')

        income_plan_map: dict[int, dict[date, Decimal]] = defaultdict(
            lambda: defaultdict(lambda: Decimal(0)),
        )

        for pln in plans_income:
            amount = pln['amount']
            income_plan_map[pln['category_income_id']][pln['date']] = (
                Decimal(str(amount)) if amount else Decimal(0)
            )

        return income_plan_map

    def aggregate_income_api(
        self,
        user: User,
        months: list[date],
        income_categories: list[IncomeCategory],
    ) -> AggregateIncomeApiDict:
        """Aggregate data for the income API view.

        Args:
            user: User to aggregate data for.
            months: List of months to aggregate.
            income_categories: List of income categories.

        Returns:
            AggregateIncomeApiDict with income API data.

        Raises:
            BudgetDataError: If validation fails.
        """
        _validate_income_api_inputs(user, months, income_categories)

        income_fact_map = self._get_income_api_facts(
            user,
            months,
            income_categories,
        )
        income_plan_map = self._get_income_api_plans(
            user,
            months,
            income_categories,
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
    type_: str,
) -> (
    QuerySet[ExpenseCategory, ExpenseCategory]
    | QuerySet[IncomeCategory, IncomeCategory]
):
    """Get categories queryset for user by type.

    Args:
        user: User to get categories for.
        type_: Category type ('expense' or 'income').

    Returns:
        QuerySet of categories filtered by type and parent_category=None.

    Raises:
        BudgetDataError: If user is None.
    """
    if user is None:
        error_msg = 'User is required.'
        raise BudgetDataError(error_msg)
    if type_ == 'expense':
        return user.category_expense_users.filter(
            parent_category=None,
        ).order_by('name')
    return user.category_income_users.filter(parent_category=None).order_by(
        'name',
    )


def _validate_budget_inputs(
    _user: User | None,
    months: list[date] | None,
    expense_categories: list[ExpenseCategory] | None,
    income_categories: list[IncomeCategory] | None,
) -> None:
    """Validate required inputs for budget aggregation.

    Args:
        _user: User instance to validate.
        months: List of months to validate.
        expense_categories: List of expense categories to validate.
        income_categories: List of income categories to validate.

    Raises:
        BudgetDataError: If any required input is None.
    """
    if _user is None:
        error_msg = 'User is required.'
        raise BudgetDataError(error_msg)
    if months is None:
        error_msg = 'Months list is required.'
        raise BudgetDataError(error_msg)
    if expense_categories is None:
        error_msg = 'Expense categories are required.'
        raise BudgetDataError(error_msg)
    if income_categories is None:
        error_msg = 'Income categories are required.'
        raise BudgetDataError(error_msg)


def _calculate_expense_totals(
    expense_fact_map: dict[int, dict[date, int]],
    expense_plan_map: dict[int, dict[date, int]],
    months: list[date],
    expense_categories: list[ExpenseCategory],
) -> tuple[list[int], list[int]]:
    """Calculate total fact and plan expenses for each month.

    Args:
        expense_fact_map: Mapping of category_id to month->fact amount.
        expense_plan_map: Mapping of category_id to month->plan amount.
        months: List of months to calculate for.
        expense_categories: List of expense categories.

    Returns:
        Tuple of (total_fact_expense, total_plan_expense) lists.
    """
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
    expense_categories: list[ExpenseCategory],
) -> list[ExpenseDataRowDict]:
    """Build expense data structure with fact, plan, diff, and percent.

    Args:
        expense_fact_map: Mapping of category_id to month->fact amount.
        expense_plan_map: Mapping of category_id to month->plan amount.
        months: List of months to build data for.
        expense_categories: List of expense categories.

    Returns:
        List of ExpenseDataRowDict with calculated values.
    """
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
    income_categories: list[IncomeCategory],
) -> tuple[list[Decimal], list[Decimal]]:
    """Calculate total fact and plan incomes for each month.

    Args:
        income_fact_map: Mapping of category_id to month->fact amount.
        income_plan_map: Mapping of category_id to month->plan amount.
        months: List of months to calculate for.
        income_categories: List of income categories.

    Returns:
        Tuple of (total_fact_income, total_plan_income) lists.
    """
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
    income_categories: list[IncomeCategory],
) -> list[IncomeDataRowDict]:
    """Build income data structure with fact, plan, diff, and percent.

    Args:
        income_fact_map: Mapping of category_id to month->fact amount.
        income_plan_map: Mapping of category_id to month->plan amount.
        months: List of months to build data for.
        income_categories: List of income categories.

    Returns:
        List of IncomeDataRowDict with calculated values.
    """
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
    """Build chart data for budget visualization.

    Args:
        months: List of months for chart.
        total_fact_income: List of total actual income per month.
        total_plan_income: List of total planned income per month.
        total_fact_expense: List of total actual expenses per month.
        total_plan_expense: List of total planned expenses per month.

    Returns:
        BudgetChartDataDict with chart visualization data.
    """
    chart_labels = [m.strftime('%b %Y') for m in months]
    chart_plan_execution_income = []
    chart_plan_execution_expense = []
    chart_balance = []

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
    """Calculate percentage of fact vs plan.

    Args:
        fact: Actual amount.
        plan: Planned amount.

    Returns:
        Percentage as Decimal (fact/plan * 100), or 0/100 if plan is 0.
    """
    if plan > 0:
        fact_decimal = Decimal(fact) if isinstance(fact, int) else fact
        plan_decimal = Decimal(plan) if isinstance(plan, int) else plan
        return (fact_decimal / plan_decimal) * 100
    return Decimal(0) if fact == 0 else Decimal(100)


def _validate_expense_table_inputs(
    _user: User | None,
    months: list[date] | None,
    expense_categories: list[ExpenseCategory] | None,
) -> None:
    """Validate required inputs for expense table aggregation.

    Args:
        _user: User instance to validate.
        months: List of months to validate.
        expense_categories: List of expense categories to validate.

    Raises:
        BudgetDataError: If any required input is None.
    """
    if _user is None:
        error_msg = 'User is required.'
        raise BudgetDataError(error_msg)
    if months is None:
        error_msg = 'Months list is required.'
        raise BudgetDataError(error_msg)
    if expense_categories is None:
        error_msg = 'Expense categories are required.'
        raise BudgetDataError(error_msg)


def _build_expense_table_data(
    expense_fact_map: dict[int, dict[date, int]],
    expense_plan_map: dict[int, dict[date, int]],
    months: list[date],
    expense_categories: list[ExpenseCategory],
) -> tuple[list[ExpenseDataRowDict], list[int], list[int]]:
    """Build expense table data structure.

    Args:
        expense_fact_map: Mapping of category_id to month->fact amount.
        expense_plan_map: Mapping of category_id to month->plan amount.
        months: List of months to build data for.
        expense_categories: List of expense categories.

    Returns:
        Tuple of (expense_data, total_fact_expense, total_plan_expense).
    """
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
    income_categories: list[IncomeCategory] | None,
) -> None:
    """Validate required inputs for income table aggregation.

    Args:
        _user: User instance to validate.
        months: List of months to validate.
        income_categories: List of income categories to validate.

    Raises:
        BudgetDataError: If any required input is None.
    """
    if _user is None:
        error_msg = 'User is required.'
        raise BudgetDataError(error_msg)
    if months is None:
        error_msg = 'Months list is required.'
        raise BudgetDataError(error_msg)
    if income_categories is None:
        error_msg = 'Income categories are required.'
        raise BudgetDataError(error_msg)


def _build_income_table_data(
    income_fact_map: dict[int, dict[date, Decimal]],
    income_plan_map: dict[int, dict[date, Decimal]],
    months: list[date],
    income_categories: list[IncomeCategory],
) -> tuple[list[IncomeDataRowDict], list[Decimal], list[Decimal]]:
    """Build income table data structure.

    Args:
        income_fact_map: Mapping of category_id to month->fact amount.
        income_plan_map: Mapping of category_id to month->plan amount.
        months: List of months to build data for.
        income_categories: List of income categories.

    Returns:
        Tuple of (income_data, total_fact_income, total_plan_income).
    """
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
    expense_categories: list[ExpenseCategory] | None,
) -> None:
    """Validate required inputs for expense API aggregation.

    Args:
        _user: User instance to validate.
        months: List of months to validate.
        expense_categories: List of expense categories to validate.

    Raises:
        BudgetDataError: If any required input is None.
    """
    if _user is None:
        error_msg = 'User is required.'
        raise BudgetDataError(error_msg)
    if months is None:
        error_msg = 'Months list is required.'
        raise BudgetDataError(error_msg)
    if expense_categories is None:
        error_msg = 'Expense categories are required.'
        raise BudgetDataError(error_msg)


def _build_income_api_data(
    income_fact_map: dict[int, dict[date, Decimal]],
    income_plan_map: dict[int, dict[date, Decimal]],
    months: list[date],
    income_categories: list[IncomeCategory],
) -> list[dict[str, Any]]:
    """Build income API data structure.

    Args:
        income_fact_map: Mapping of category_id to month->fact amount.
        income_plan_map: Mapping of category_id to month->plan amount.
        months: List of months to build data for.
        income_categories: List of income categories.

    Returns:
        List of dictionaries with income API data.
    """
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
    expense_categories: list[ExpenseCategory],
) -> list[dict[str, Any]]:
    """Build expense API data structure.

    Args:
        expense_fact_map: Mapping of category_id to month->fact amount.
        expense_plan_map: Mapping of category_id to month->plan amount.
        months: List of months to build data for.
        expense_categories: List of expense categories.

    Returns:
        List of dictionaries with expense API data.
    """
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
    income_categories: list[IncomeCategory] | None,
) -> None:
    """Validate required inputs for income API aggregation.

    Args:
        _user: User instance to validate.
        months: List of months to validate.
        income_categories: List of income categories to validate.

    Raises:
        BudgetDataError: If any required input is None.
    """
    if _user is None:
        error_msg = 'User is required.'
        raise BudgetDataError(error_msg)
    if months is None:
        error_msg = 'Months list is required.'
        raise BudgetDataError(error_msg)
    if income_categories is None:
        error_msg = 'Income categories are required.'
        raise BudgetDataError(error_msg)
