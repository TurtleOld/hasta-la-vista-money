import json
from datetime import date
from decimal import Decimal
from typing import Any, ClassVar, TypedDict, overload

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import ListView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from hasta_la_vista_money.budget.models import DateList, Planning
from hasta_la_vista_money.budget.services.budget import (
    aggregate_budget_data,
    aggregate_expense_api,
    aggregate_expense_table,
    aggregate_income_api,
    aggregate_income_table,
    get_categories,
)
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.services.generate_dates import generate_date_list
from hasta_la_vista_money.users.models import User


@overload
def get_fact_amount(
    user: User,
    category: ExpenseCategory,
    month: date,
    type_: str,
) -> Decimal | int: ...


@overload
def get_fact_amount(
    user: User,
    category: IncomeCategory,
    month: date,
    type_: str,
) -> Decimal | int: ...


def get_fact_amount(
    user: User,
    category: ExpenseCategory | IncomeCategory,
    month: date,
    type_: str,
) -> Decimal | int:
    if type_ == 'expense':
        if isinstance(category, ExpenseCategory):
            return (
                Expense.objects.filter(
                    user=user,
                    category=category,
                    date__year=month.year,
                    date__month=month.month,
                )
                .select_related('user', 'category')
                .aggregate(total=Sum('amount'))['total']
                or 0
            )
        raise ValueError('Expected ExpenseCategory for expense type')
    if isinstance(category, IncomeCategory):
        return (
            Income.objects.filter(
                user=user,
                category=category,
                date__year=month.year,
                date__month=month.month,
            )
            .select_related('user', 'category')
            .aggregate(total=Sum('amount'))['total']
            or 0
        )
    raise ValueError('Expected IncomeCategory for income type')


def get_plan_amount(
    user: User,
    category: ExpenseCategory | IncomeCategory,
    month: date,
    type_: str,
) -> Decimal | int:
    q = Planning.objects.filter(
        user=user,
        date=month,
        type=type_,
    ).select_related('user', 'category_expense', 'category_income')
    if type_ == 'expense':
        if isinstance(category, ExpenseCategory):
            q = q.filter(category_expense=category)
        else:
            raise ValueError('Expected ExpenseCategory for expense type')
    elif isinstance(category, IncomeCategory):
        q = q.filter(category_income=category)
    else:
        raise ValueError('Expected IncomeCategory for income type')
    plan = q.first()
    return plan.amount if plan else 0


class BaseView:
    template_name = 'budget.html'


class BudgetContextMixin:
    """
    Mixin to provide user, months, expense and income categories
    for budget views.
    """

    def get_budget_context(self):
        user = get_object_or_404(User, username=self.request.user)
        list_dates = DateList.objects.filter(user=user).order_by('date')
        months = [d.date for d in list_dates]
        expense_categories = list(get_categories(user, 'expense'))
        income_categories = list(get_categories(user, 'income'))
        return user, months, expense_categories, income_categories


class BudgetView(LoginRequiredMixin, BudgetContextMixin, BaseView, ListView):
    model = Planning

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """
        Returns context data for the budget page, using aggregated data
        from service layer.
        """
        context = super().get_context_data(**kwargs)
        user, months, expense_categories, income_categories = (
            self.get_budget_context()
        )
        context.update(
            aggregate_budget_data(
                user=user,
                months=months,
                expense_categories=expense_categories,
                income_categories=income_categories,
            ),
        )
        return context


def generate_date_list_view(request):
    """Функция представления генерации дат."""
    if request.method == 'POST':
        user = request.user
        queryset_user = get_object_or_404(User, username=user)
        last_date_obj = queryset_user.budget_date_lists.last()
        if last_date_obj:
            queryset_last_date = last_date_obj.date
        else:
            queryset_last_date = date.today().replace(day=1)
        type_ = request.POST.get('type')
        generate_date_list(queryset_last_date, queryset_user, type_)
        if type_ == 'income':
            return redirect(reverse_lazy('budget:income_table'))
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
            amount = Decimal(0)
        type_ = data['type']
        if type_ == 'expense':
            category = get_object_or_404(
                ExpenseCategory,
                id=data['category_id'],
            )
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


class ExpenseTableView(
    LoginRequiredMixin,
    BudgetContextMixin,
    BaseView,
    ListView,
):
    model = Planning
    template_name = 'expense_table.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """
        Returns context data for the expense table page, using aggregated
        data from service layer.
        """
        context = super().get_context_data(**kwargs)
        user, months, expense_categories, _ = self.get_budget_context()
        context.update(
            aggregate_expense_table(
                user=user,
                months=months,
                expense_categories=expense_categories,
            ),
        )
        return context


class IncomeTableView(
    LoginRequiredMixin,
    BudgetContextMixin,
    BaseView,
    ListView,
):
    model = Planning
    template_name = 'income_table.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """
        Returns context data for the income table page, using aggregated
        data from service layer.
        """
        context = super().get_context_data(**kwargs)
        user, months, _, income_categories = self.get_budget_context()
        context.update(
            aggregate_income_table(
                user=user,
                months=months,
                income_categories=income_categories,
            ),
        )
        return context


class PlanningExpenseDict(TypedDict):
    category_expense_id: int
    date: date
    amount: Decimal


class ExpenseBudgetAPIView(APIView):
    permission_classes: ClassVar[list] = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        """
        Returns aggregated expense data for API response.
        """
        user = request.user
        list_dates = DateList.objects.filter(user=user).order_by('date')
        months = [d.date.replace(day=1) for d in list_dates]
        expense_categories = list(get_categories(user, 'expense'))
        data = aggregate_expense_api(
            user=user,
            months=months,
            expense_categories=expense_categories,
        )
        return Response(data)


class IncomeBudgetAPIView(APIView):
    permission_classes: ClassVar[list] = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        """
        Returns aggregated income data for API response.
        """
        user = request.user
        list_dates = DateList.objects.filter(user=user).order_by('date')
        months = [d.date.replace(day=1) for d in list_dates]
        income_categories = list(get_categories(user, 'income'))
        data = aggregate_income_api(
            user=user,
            months=months,
            income_categories=income_categories,
        )
        return Response(data)
