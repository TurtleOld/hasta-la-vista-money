from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import QuerySet, Sum
from django.db.models.functions import TruncMonth

from hasta_la_vista_money.budget.models import Planning
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.users.models import User


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
        raise BudgetDataError('User is required for category lookup.')
    if type_ == 'expense':
        return user.category_expense_users.filter(
            parent_category=None,
        ).order_by('name')
    return user.category_income_users.filter(parent_category=None).order_by(
        'name',
    )


def aggregate_budget_data(
    user: User,
    months: list[date],
    expense_categories: list[ExpenseCategory],
    income_categories: list[IncomeCategory],
) -> dict[str, Any]:
    """
    Aggregates all budget data for context: expenses, incomes, plans,
    diffs, percents, and chart data.
    Raises BudgetDataError if required data is missing.
    """
    if not user:
        raise BudgetDataError('User is required for budget aggregation.')
    if months is None:
        raise BudgetDataError('Months list is required.')
    if expense_categories is None or income_categories is None:
        raise BudgetDataError('Expense and income categories are required.')
    # Expenses
    if months:
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
    else:
        expenses = []
    expense_fact_map: dict[int, dict[date, int]] = defaultdict(
        lambda: defaultdict(lambda: 0),
    )
    for e in expenses:
        month_date = (
            e['month'].date() if hasattr(e['month'], 'date') else e['month']
        )
        month_start = month_date.replace(day=1)
        expense_fact_map[e['category_id']][month_start] = e['total'] or 0
    total_fact_expense = [0] * len(months)
    for i, m in enumerate(months):
        for cat in expense_categories:
            total_fact_expense[i] += expense_fact_map[cat.id][m]
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
    expense_data = []
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
            total_plan_expense[i] += plan or 0
        expense_data.append(row)

    # Incomes
    if months:
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
    else:
        income_queryset = []
    income_fact_map: dict[int, dict[date, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal(0)),
    )
    for e in income_queryset:
        month_date = (
            e['month'].date() if hasattr(e['month'], 'date') else e['month']
        )
        income_fact_map[e['category_id']][month_date] = e['total'] or Decimal(
            0,
        )
    total_fact_income = [0] * len(months)
    for i, m in enumerate(months):
        for cat in income_categories:
            total_fact_income[i] += income_fact_map[cat.id][m]
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
    income_data = []
    total_plan_income = [0] * len(months)
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
            total_plan_income[i] += plan
        income_data.append(row)

    # Chart data
    chart_labels = [m.strftime('%b %Y') for m in months]
    chart_plan_execution_income = []
    chart_plan_execution_expense = []
    for i in range(len(months)):
        if total_plan_income[i] > 0:
            income_percent = (total_fact_income[i] / total_plan_income[i]) * 100
        else:
            income_percent = 0 if total_fact_income[i] == 0 else 100
        chart_plan_execution_income.append(float(income_percent))
        if total_plan_expense[i] > 0:
            expense_percent = (
                total_fact_expense[i] / total_plan_expense[i]
            ) * 100
        else:
            expense_percent = 0 if total_fact_expense[i] == 0 else 100
        chart_plan_execution_expense.append(float(expense_percent))

    return {
        'chart_labels': chart_labels,
        'chart_plan_execution_income': chart_plan_execution_income,
        'chart_plan_execution_expense': chart_plan_execution_expense,
        'months': months,
        'expense_data': expense_data,
        'income_data': income_data,
        'total_fact_expense': total_fact_expense,
        'total_plan_expense': total_plan_expense,
        'total_fact_income': total_fact_income,
        'total_plan_income': total_plan_income,
    }


def aggregate_expense_table(
    user: User,
    months: list[date],
    expense_categories: list[ExpenseCategory],
) -> dict[str, Any]:
    """
    Aggregates data for the expense table view.
    Raises BudgetDataError if required data is missing.
    """
    if not user:
        raise BudgetDataError('User is required for expense table aggregation.')
    if months is None:
        raise BudgetDataError('Months list is required.')
    if expense_categories is None:
        raise BudgetDataError('Expense categories are required.')
    if months:
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
    else:
        expenses = []
    expense_fact_map = defaultdict(lambda: defaultdict(lambda: 0))
    for e in expenses:
        month_date = (
            e['month'].date() if hasattr(e['month'], 'date') else e['month']
        )
        expense_fact_map[e['category_id']][month_date] = e['total'] or 0
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
    return {
        'months': months,
        'expense_data': expense_data,
        'total_fact_expense': total_fact_expense,
        'total_plan_expense': total_plan_expense,
    }


def aggregate_income_table(
    user: User,
    months: list[date],
    income_categories: list[IncomeCategory],
) -> dict[str, Any]:
    """
    Aggregates data for the income table view.
    Raises BudgetDataError if required data is missing.
    """
    if not user:
        raise BudgetDataError('User is required for income table aggregation.')
    if months is None:
        raise BudgetDataError('Months list is required.')
    if income_categories is None:
        raise BudgetDataError('Income categories are required.')
    if months:
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
    else:
        income_queryset = []
    income_fact_map = defaultdict(lambda: defaultdict(lambda: Decimal(0)))
    for e in income_queryset:
        month_date = (
            e['month'].date() if hasattr(e['month'], 'date') else e['month']
        )
        income_fact_map[e['category_id']][month_date] = e['total'] or Decimal(
            0,
        )
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
    return {
        'months': months,
        'income_data': income_data,
        'total_fact_income': total_fact_income,
        'total_plan_income': total_plan_income,
    }


def aggregate_expense_api(
    user: User,
    months: list[date],
    expense_categories: list[ExpenseCategory],
) -> dict[str, Any]:
    """
    Aggregates data for the expense API view.
    Raises BudgetDataError if required data is missing.
    """
    if not user:
        raise BudgetDataError('User is required for expense API aggregation.')
    if months is None:
        raise BudgetDataError('Months list is required.')
    if expense_categories is None:
        raise BudgetDataError('Expense categories are required.')
    if months:
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
    else:
        expenses = []
    expense_fact_map = defaultdict(lambda: defaultdict(lambda: 0))
    for e in expenses:
        month_date = (
            e['month'].date() if hasattr(e['month'], 'date') else e['month']
        )
        month_start = month_date.replace(day=1)
        expense_fact_map[e['category_id']][month_start] = e['total'] or 0
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
    return {'months': [m.isoformat() for m in months], 'data': data}


def aggregate_income_api(
    user: User,
    months: list[date],
    income_categories: list[IncomeCategory],
) -> dict[str, Any]:
    """
    Aggregates data for the income API view.
    Raises BudgetDataError if required data is missing.
    """
    if not user:
        raise BudgetDataError('User is required for income API aggregation.')
    if months is None:
        raise BudgetDataError('Months list is required.')
    if income_categories is None:
        raise BudgetDataError('Income categories are required.')
    if months:
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
    else:
        incomes = []
    income_fact_map = defaultdict(lambda: defaultdict(lambda: 0))
    for e in incomes:
        month_date = (
            e['month'].date() if hasattr(e['month'], 'date') else e['month']
        )
        month_start = month_date.replace(day=1)
        income_fact_map[e['category_id']][month_start] = e['total'] or 0
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
    return {'months': [m.isoformat() for m in months], 'data': data}
