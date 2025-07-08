import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, TypedDict, Union, overload

from django.db.models import QuerySet, Sum
from django.db.models.functions import TruncMonth
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import ListView
from hasta_la_vista_money.budget.models import DateList, Planning
from hasta_la_vista_money.services.generate_dates import generate_date_list
from hasta_la_vista_money.custom_mixin import CustomNoPermissionMixin
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.users.models import User


@overload
def get_fact_amount(
    user: User,
    category: ExpenseCategory,
    month: date,
    type_: str,
) -> Union[Decimal, int]: ...


@overload
def get_fact_amount(
    user: User,
    category: IncomeCategory,
    month: date,
    type_: str,
) -> Union[Decimal, int]: ...


def get_fact_amount(
    user: User,
    category: Union[ExpenseCategory, IncomeCategory],
    month: date,
    type_: str,
) -> Union[Decimal, int]:
    if type_ == 'expense':
        if isinstance(category, ExpenseCategory):
            return (
                Expense.objects.filter(
                    user=user,
                    category=category,
                    date__year=month.year,
                    date__month=month.month,
                ).aggregate(total=Sum('amount'))['total']
                or 0
            )
        else:
            raise ValueError('Expected ExpenseCategory for expense type')
    else:
        if isinstance(category, IncomeCategory):
            return (
                Income.objects.filter(
                    user=user,
                    category=category,
                    date__year=month.year,
                    date__month=month.month,
                ).aggregate(total=Sum('amount'))['total']
                or 0
            )
        else:
            raise ValueError('Expected IncomeCategory for income type')


def get_plan_amount(
    user: User,
    category: Union[ExpenseCategory, IncomeCategory],
    month: date,
    type_: str,
) -> Union[Decimal, int]:
    q = Planning.objects.filter(
        user=user,
        date=month,
        type=type_,
    )
    if type_ == 'expense':
        if isinstance(category, ExpenseCategory):
            q = q.filter(category_expense=category)
        else:
            raise ValueError('Expected ExpenseCategory for expense type')
    else:
        if isinstance(category, IncomeCategory):
            q = q.filter(category_income=category)
        else:
            raise ValueError('Expected IncomeCategory for income type')
    plan = q.first()
    return plan.amount if plan else 0


def get_categories(user: User, type_: str) -> QuerySet:
    if type_ == 'expense':
        return user.category_expense_users.filter(parent_category=None).order_by('name')
    else:
        return user.category_income_users.filter(parent_category=None).order_by('name')


class BaseView:
    template_name = 'budget.html'


class BudgetView(CustomNoPermissionMixin, BaseView, ListView):
    model = Planning

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = get_object_or_404(User, username=self.request.user)
        list_dates = DateList.objects.filter(user=user).order_by('date')
        months = [d.date for d in list_dates]

        expense_categories = list(get_categories(user, 'expense'))
        income_categories = list(get_categories(user, 'income'))

        if months:
            expenses: Union[QuerySet[Expense, Dict[str, Any]], List[Dict[str, Any]]] = (
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
        expense_fact_map: Dict[int, Dict[date, int]] = defaultdict(
            lambda: defaultdict(lambda: 0),
        )
        for e in expenses:
            month_date = (
                e['month'].date() if hasattr(e['month'], 'date') else e['month']
            )
            expense_fact_map[e['category_id']][month_date] = e['total'] or 0
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
        expense_plan_map: Dict[int, Dict[date, int]] = defaultdict(
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

        income_queryset: Union[QuerySet[Income, Dict[str, Any]], List[Dict[str, Any]]]
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
        income_fact_map: Dict[int, Dict[date, Decimal]] = defaultdict(
            lambda: defaultdict(lambda: Decimal('0')),
        )
        for e in income_queryset:
            month_date = (
                e['month'].date() if hasattr(e['month'], 'date') else e['month']
            )
            income_fact_map[e['category_id']][month_date] = e['total'] or Decimal('0')
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
            income_plan_map[p['category_income_id']][p['date']] = p['amount'] or 0

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
                expense_percent = (total_fact_expense[i] / total_plan_expense[i]) * 100
            else:
                expense_percent = 0 if total_fact_expense[i] == 0 else 100
            chart_plan_execution_expense.append(float(expense_percent))

        context['chart_labels'] = chart_labels
        context['chart_plan_execution_income'] = chart_plan_execution_income
        context['chart_plan_execution_expense'] = chart_plan_execution_expense
        context['months'] = months
        context['expense_data'] = expense_data
        context['income_data'] = income_data
        context['total_fact_expense'] = total_fact_expense
        context['total_plan_expense'] = total_plan_expense
        context['total_fact_income'] = total_fact_income
        context['total_plan_income'] = total_plan_income

        return context


def generate_date_list_view(request):
    """Функция представления генерации дат."""
    if request.method == 'POST':
        user = request.user
        queryset_user = get_object_or_404(User, username=user)
        last_date_obj = queryset_user.budget_date_list_users.last()
        if last_date_obj:
            queryset_last_date = last_date_obj.date
        else:
            queryset_last_date = date.today().replace(day=1)
        type_ = request.POST.get('type')
        generate_date_list(queryset_last_date, queryset_user, type_)
        if type_ == 'income':
            return redirect(reverse_lazy('budget:income_table'))
        else:
            return redirect(reverse_lazy('budget:expense_table'))


def change_planning(request):
    """Функция для изменения сумм планирования."""
    try:
        data = json.loads(request.body.decode('utf-8'))
        planning_value = data.get('planning')
        return JsonResponse({'planning_value': planning_value})
    except json.JSONDecodeError:
        return JsonResponse({'error': 'error'})


def save_planning(request):
    """AJAX: сохранить план по категории, месяцу, типу (расход/доход)"""
    if (
        request.method == 'POST'
        and request.headers.get('x-requested-with') == 'XMLHttpRequest'
    ):
        data = json.loads(request.body.decode('utf-8'))
        user = request.user
        month = date.fromisoformat(data['month'])
        try:
            amount = Decimal(str(data['amount']))
        except Exception:
            amount = Decimal('0')
        type_ = data['type']
        if type_ == 'expense':
            category = get_object_or_404(ExpenseCategory, id=data['category_id'])
            plan, created = Planning.objects.get_or_create(
                user=user,
                category_expense=category,
                date=month,
                type=type_,
                defaults={'amount': amount},
            )
        else:
            category = get_object_or_404(IncomeCategory, id=data['category_id'])
            plan, created = Planning.objects.get_or_create(
                user=user,
                category_income=category,
                date=month,
                type=type_,
                defaults={'amount': amount},
            )
        if not created:
            plan.amount = amount
            plan.save()
        return JsonResponse({'success': True, 'amount': str(plan.amount)})
    return JsonResponse({'success': False, 'error': 'Invalid request'})


class ExpenseTableView(CustomNoPermissionMixin, BaseView, ListView):
    model = Planning
    template_name = 'expense_table.html'

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = get_object_or_404(User, username=self.request.user)
        list_dates = DateList.objects.filter(user=user).order_by('date')
        months = [d.date for d in list_dates]
        expense_categories = list(get_categories(user, 'expense'))
        if months:
            expenses: Union[QuerySet[Expense, Dict[str, Any]], List[Dict[str, Any]]] = (
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
            expenses: Union[
                QuerySet[Expense, Dict[str, Any]],
                List[Dict[str, Any]],
            ] = []
        expense_fact_map = defaultdict(lambda: defaultdict(lambda: 0))
        for e in expenses:
            month_date = (
                e['month'].date() if hasattr(e['month'], 'date') else e['month']
            )
            expense_fact_map[e['category_id']][month_date] = e['total'] or 0
        plans_expense: QuerySet[Planning, dict[str, Any]] = Planning.objects.filter(
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
        total_fact_expense: list[int] = [0] * len(months)
        total_plan_expense: list[int] = [0] * len(months)
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
                fact: int = expense_fact_map[cat.id][m]
                plan: int = expense_plan_map[cat.id][m]
                diff = fact - plan
                percent = (fact / plan * 100) if plan else None
                row['fact'].append(fact)
                row['plan'].append(plan)
                row['diff'].append(diff)
                row['percent'].append(percent)
                total_fact_expense[i] += fact
                total_plan_expense[i] += plan
            expense_data.append(row)
        context['months'] = months
        context['expense_data'] = expense_data
        context['total_fact_expense'] = total_fact_expense
        context['total_plan_expense'] = total_plan_expense
        return context


class IncomeTableView(CustomNoPermissionMixin, BaseView, ListView):
    model = Planning
    template_name = 'income_table.html'

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = get_object_or_404(User, username=self.request.user)
        list_dates = DateList.objects.filter(user=user).order_by('date')
        months: List[date] = [d.date for d in list_dates]
        income_categories = list(get_categories(user, 'income'))
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
            income_queryset = Income.objects.none()
        income_fact_map: Dict[int, Dict[date, Decimal]] = defaultdict(
            lambda: defaultdict(lambda: Decimal('0')),
        )
        for e in income_queryset:
            month_date = (
                e['month'].date() if hasattr(e['month'], 'date') else e['month']
            )
            income_fact_map[e['category_id']][month_date] = e['total'] or Decimal('0')
        plans_inc = Planning.objects.filter(
            user=user,
            date__in=months,
            type='income',
            category_income__in=income_categories,
        ).values('category_income_id', 'date', 'amount')
        income_plan_map: Dict[int, Dict[date, Decimal]] = defaultdict(
            lambda: defaultdict(lambda: Decimal('0')),
        )
        for p in plans_inc:
            income_plan_map[p['category_income_id']][p['date']] = p[
                'amount'
            ] or Decimal('0')
        income_data: List[Dict[str, Any]] = []
        total_fact_income: List[Decimal] = [Decimal('0')] * len(months)
        total_plan_income: List[Decimal] = [Decimal('0')] * len(months)
        for cat in income_categories:
            row: Dict[str, Any] = {
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
        context['months'] = months
        context['income_data'] = income_data
        context['total_fact_income'] = total_fact_income
        context['total_plan_income'] = total_plan_income
        return context


class PlanningExpenseDict(TypedDict):
    category_expense_id: int
    date: date
    amount: Decimal
