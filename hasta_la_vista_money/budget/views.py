from datetime import date
from datetime import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TypedDict, cast, overload

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import ListView, View
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from hasta_la_vista_money.authentication.authentication import (
    CookieJWTAuthentication,
)
from hasta_la_vista_money.budget.models import Planning
from hasta_la_vista_money.budget.repositories import (
    PlanningRepository,
)
from hasta_la_vista_money.budget.services.budget import (
    get_categories,
)
from hasta_la_vista_money.expense.models import ExpenseCategory

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer
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
            'expense_repository and income_repository must be provided',
        )

    if type_ == 'expense':
        if isinstance(category, ExpenseCategory):
            qs_expense = expense_repository.filter_by_user_category_and_month(
                user,
                category,
                month,
            )
            return qs_expense.aggregate(total=Sum('amount'))['total'] or 0
        error_msg = 'Expected ExpenseCategory for expense type'
        raise ValueError(error_msg)
    if isinstance(category, IncomeCategory):
        qs_income = income_repository.filter_by_user_category_and_month(
            user,
            category,
            month,
        )
        return qs_income.aggregate(total=Sum('amount'))['total'] or 0
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
        user,
        category,
        month,
        type_,
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

    def get_budget_context(
        self,
    ) -> tuple[User, list[date], list[ExpenseCategory], list[IncomeCategory]]:
        request_obj = getattr(self, 'request', None)
        if request_obj is None:
            raise AttributeError('request attribute is required')
        request = cast('RequestWithContainer', request_obj)
        user = get_object_or_404(User, username=request.user)
        date_list_repository = request.container.budget.date_list_repository()
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
        request = cast('RequestWithContainer', self.request)
        budget_service = request.container.budget.budget_service()
        context.update(
            budget_service.aggregate_budget_data(
                user=user,
                months=months,
                expense_categories=expense_categories,
                income_categories=income_categories,
            ),
        )
        return context


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
        request = cast('RequestWithContainer', self.request)
        budget_service = request.container.budget.budget_service()
        context.update(
            budget_service.aggregate_expense_table(
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
        request = cast('RequestWithContainer', self.request)
        budget_service = request.container.budget.budget_service()
        context.update(
            budget_service.aggregate_income_table(
                user=user,
                months=months,
                income_categories=income_categories,
            ),
        )
        return context


class GenerateDateView(LoginRequiredMixin, View):
    """View for generating date list for both expense and income types."""

    def post(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        """Generate date list for both expense and income types.

        Args:
            request: HTTP request.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            Redirect to budget list page.
        """
        user = cast('User', request.user)
        queryset_user = get_object_or_404(User, username=user)

        last_date_obj = queryset_user.budget_date_lists.last()
        if last_date_obj:
            queryset_last_date = timezone.make_aware(
                dt.combine(last_date_obj.date, dt.min.time()),
            )
        else:
            queryset_last_date = timezone.now().replace(day=1)

        generate_date_list(queryset_last_date, queryset_user, 'expense')
        generate_date_list(queryset_last_date, queryset_user, 'income')

        return redirect('budget:list')


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
    authentication_classes = (CookieJWTAuthentication,)
    permission_classes = [IsAuthenticated]
    throttle_classes = (UserRateThrottle,)

    def get(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """
        Returns aggregated expense data for API response.
        """
        user = request.user
        request_with_container = cast('RequestWithContainer', request)
        date_list_repository = (
            request_with_container.container.budget.date_list_repository()
        )
        list_dates = date_list_repository.get_by_user_ordered(user)
        months = [d.date.replace(day=1) for d in list_dates]
        expense_categories = cast(
            'list[ExpenseCategory]',
            list(get_categories(user, 'expense')),
        )
        budget_service = (
            request_with_container.container.budget.budget_service()
        )
        data = budget_service.aggregate_expense_api(
            user=user,
            months=months,
            expense_categories=expense_categories,
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
    authentication_classes = (CookieJWTAuthentication,)
    permission_classes = [IsAuthenticated]
    throttle_classes = (UserRateThrottle,)

    def get(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """
        Returns aggregated income data for API response.
        """
        user = request.user
        request_with_container = cast('RequestWithContainer', request)
        date_list_repository = (
            request_with_container.container.budget.date_list_repository()
        )
        list_dates = date_list_repository.get_by_user_ordered(user)
        months = [d.date.replace(day=1) for d in list_dates]
        income_categories = cast(
            'list[IncomeCategory]',
            list(get_categories(user, 'income')),
        )
        budget_service = (
            request_with_container.container.budget.budget_service()
        )
        data = budget_service.aggregate_income_api(
            user=user,
            months=months,
            income_categories=income_categories,
        )
        return Response(data)
