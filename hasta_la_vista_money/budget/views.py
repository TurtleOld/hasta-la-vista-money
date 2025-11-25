import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, TypedDict, cast, overload

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum
from django.http import HttpRequest, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import ListView
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from hasta_la_vista_money.budget.models import Planning
from hasta_la_vista_money.budget.repositories import (
    PlanningRepository,
)
from hasta_la_vista_money.budget.services.budget import (
    aggregate_budget_data,
    aggregate_expense_api,
    aggregate_expense_table,
    aggregate_income_api,
    aggregate_income_table,
    get_categories,
)
from hasta_la_vista_money.expense.models import ExpenseCategory
from hasta_la_vista_money.expense.repositories import ExpenseRepository
from hasta_la_vista_money.income.models import IncomeCategory
from hasta_la_vista_money.income.repositories import IncomeRepository
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
    expense_repository: ExpenseRepository | None = None,
    income_repository: IncomeRepository | None = None,
) -> Decimal | int:
    if expense_repository is None or income_repository is None:
        raise ValueError(
            'expense_repository and income_repository must be provided'
        )

    if type_ == 'expense':
        if isinstance(category, ExpenseCategory):
            qs = expense_repository.filter_by_user_category_and_month(
                user, category, month
            )
            return qs.aggregate(total=Sum('amount'))['total'] or 0
        error_msg = 'Expected ExpenseCategory for expense type'
        raise ValueError(error_msg)
    if isinstance(category, IncomeCategory):
        qs = income_repository.filter_by_user_category_and_month(
            user, category, month
        )
        return qs.aggregate(total=Sum('amount'))['total'] or 0
    error_msg = 'Expected IncomeCategory for income type'
    raise ValueError(error_msg)


def get_plan_amount(
    user: User,
    category: ExpenseCategory | IncomeCategory,
    month: date,
    type_: str,
    planning_repository: PlanningRepository | None = None,
) -> Decimal | int:
    if planning_repository is None:
        raise ValueError('planning_repository must be provided')

    plan = planning_repository.filter_by_user_category_and_month(
        user, category, month, type_
    )
    if plan:
        return Decimal(str(plan.amount))
    return 0


class BaseView:
    template_name = 'budget.html'


class BudgetContextMixin:
    """
    Mixin to provide user, months, expense and income categories
    for budget views.
    """

    request: HttpRequest

    def get_budget_context(
        self,
    ) -> tuple[User, list[date], list[ExpenseCategory], list[IncomeCategory]]:
        user = get_object_or_404(User, username=self.request.user)
        date_list_repository = (
            self.request.container.budget.date_list_repository()
        )
        list_dates = date_list_repository.get_by_user_ordered(user)
        months = [d.date for d in list_dates]
        expense_categories = cast(
            'list[ExpenseCategory]',
            list(get_categories(user, 'expense')),
        )
        income_categories = cast(
            'list[IncomeCategory]',
            list(get_categories(user, 'income')),
        )
        return user, months, expense_categories, income_categories


class BudgetView(
    LoginRequiredMixin,
    BudgetContextMixin,
    BaseView,
    ListView[Planning],
):
    model = Planning
    template_name = 'budget.html'

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
                container=self.request.container,
            ),
        )
        return context


def generate_date_list_view(request: HttpRequest) -> HttpResponseRedirect:
    """Функция представления генерации дат."""
    if request.method == 'POST':
        user = request.user
        queryset_user = get_object_or_404(User, username=user)
        last_date_obj = queryset_user.budget_date_lists.last()
        if last_date_obj:
            queryset_last_date = timezone.make_aware(
                datetime.combine(last_date_obj.date, datetime.min.time()),
            )
        else:
            queryset_last_date = timezone.now().replace(day=1)
        type_ = request.POST.get('type')
        generate_date_list(queryset_last_date, queryset_user, type_)
        if type_ == 'income':
            return redirect(reverse_lazy('budget:income_table'))
        return redirect(reverse_lazy('budget:expense_table'))

    return redirect(reverse_lazy('budget:expense_table'))


def change_planning(request: HttpRequest) -> JsonResponse:
    """Функция для изменения сумм планирования."""
    try:
        data = json.loads(request.body.decode('utf-8'))
        planning_value = data.get('planning')
        return JsonResponse({'planning_value': planning_value})
    except json.JSONDecodeError:
        return JsonResponse({'error': 'error'})


def save_planning(request: HttpRequest) -> JsonResponse:
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
        except (ValueError, TypeError, KeyError):
            amount = Decimal(0)
        type_ = data['type']
        planning_repository = request.container.budget.planning_repository()
        if type_ == 'expense':
            expense_category = get_object_or_404(
                ExpenseCategory,
                id=data['category_id'],
            )
            plan, created = planning_repository.get_or_create_planning(
                user=user,
                category_expense=expense_category,
                date=month,
                planning_type=type_,
                defaults={'amount': amount},
            )
        else:
            income_category = get_object_or_404(
                IncomeCategory,
                id=data['category_id'],
            )
            plan, created = planning_repository.get_or_create_planning(
                user=user,
                category_income=income_category,
                date=month,
                planning_type=type_,
                defaults={'amount': amount},
            )
        if not created:
            plan.amount = Decimal(str(amount))
            plan.save()
        return JsonResponse({'success': True, 'amount': str(plan.amount)})
    return JsonResponse({'success': False, 'error': 'Invalid request'})


class ExpenseTableView(
    LoginRequiredMixin,
    BudgetContextMixin,
    BaseView,
    ListView[Planning],
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
                container=self.request.container,
            ),
        )
        return context


class IncomeTableView(
    LoginRequiredMixin,
    BudgetContextMixin,
    BaseView,
    ListView[Planning],
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
                container=self.request.container,
            ),
        )
        return context


class PlanningExpenseDict(TypedDict):
    category_expense_id: int
    date: date
    amount: Decimal


@extend_schema(
    tags=['budget'],
    summary='Данные расходов для бюджета',
    description=(
        'Получить агрегированные данные расходов по категориям и месяцам'
    ),
    responses={
        200: OpenApiResponse(
            description='Агрегированные данные расходов',
            response={
                'type': 'object',
                'properties': {
                    'months': {
                        'type': 'array',
                        'items': {'type': 'string', 'format': 'date'},
                    },
                    'categories': {
                        'type': 'array',
                        'items': {'type': 'string'},
                    },
                    'data': {
                        'type': 'array',
                        'items': {'type': 'object'},
                    },
                },
            },
        ),
    },
)
class ExpenseBudgetAPIView(APIView):
    schema = AutoSchema()
    permission_classes = [IsAuthenticated]

    def get(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """
        Returns aggregated expense data for API response.
        """
        user = request.user
        date_list_repository = (
            self.request.container.budget.date_list_repository()
        )
        list_dates = date_list_repository.get_by_user_ordered(user)
        months = [d.date.replace(day=1) for d in list_dates]
        expense_categories = cast(
            'list[ExpenseCategory]',
            list(get_categories(user, 'expense')),
        )
        data = aggregate_expense_api(
            user=user,
            months=months,
            expense_categories=expense_categories,
            container=self.request.container,
        )
        return Response(data)


@extend_schema(
    tags=['budget'],
    summary='Данные доходов для бюджета',
    description=(
        'Получить агрегированные данные доходов по категориям и месяцам'
    ),
    responses={
        200: OpenApiResponse(
            description='Агрегированные данные доходов',
            response={
                'type': 'object',
                'properties': {
                    'months': {
                        'type': 'array',
                        'items': {'type': 'string', 'format': 'date'},
                    },
                    'categories': {
                        'type': 'array',
                        'items': {'type': 'string'},
                    },
                    'data': {
                        'type': 'array',
                        'items': {'type': 'object'},
                    },
                },
            },
        ),
    },
)
class IncomeBudgetAPIView(APIView):
    schema = AutoSchema()
    permission_classes = [IsAuthenticated]

    def get(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """
        Returns aggregated income data for API response.
        """
        user = request.user
        date_list_repository = (
            self.request.container.budget.date_list_repository()
        )
        list_dates = date_list_repository.get_by_user_ordered(user)
        months = [d.date.replace(day=1) for d in list_dates]
        income_categories = cast(
            'list[IncomeCategory]',
            list(get_categories(user, 'income')),
        )
        data = aggregate_income_api(
            user=user,
            months=months,
            income_categories=income_categories,
            container=self.request.container,
        )
        return Response(data)
