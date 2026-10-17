from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TypedDict, cast

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404
from django.views.generic import ListView
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
from hasta_la_vista_money.budget.presentation import build_budget_matrix_context
from hasta_la_vista_money.budget.services.budget import (
    get_categories,
)
from hasta_la_vista_money.finance_account.analytics_currency import (
    AnalyticsCurrency,
    get_analytics_currency,
)
from hasta_la_vista_money.transactions.models import Category
from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.users.services.groups import (
    get_family_groups,
    readable_users,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer


class BudgetScopeChoiceDict(TypedDict):
    value: str
    label: str


class BudgetPageContextDict(TypedDict):
    user: User
    months: list[date]
    expense_categories: list[Category]
    income_categories: list[Category]
    scope_users: list[User]
    budget_scope: str
    budget_scope_choices: list[BudgetScopeChoiceDict]
    analytics_currency: AnalyticsCurrency


def _normalize_budget_scope(value: str | None) -> str:
    if value == 'family':
        return 'family'
    return 'my'


def _scope_choices(
    user: User,
    request: Any,
) -> list[BudgetScopeChoiceDict]:
    family_groups = get_family_groups(user, request)
    choices: list[BudgetScopeChoiceDict] = [
        {'value': 'my', 'label': 'Мой бюджет'},
    ]
    if family_groups:
        choices.append({'value': 'family', 'label': 'Семья'})
    return choices


def _resolve_budget_scope(
    user: User,
    request: Any,
) -> tuple[str, list[User], list[BudgetScopeChoiceDict]]:
    choices = _scope_choices(user, request)
    allowed_scopes = {choice['value'] for choice in choices}
    raw_scope = request.GET.get('scope')
    request_data = getattr(request, 'data', None)
    request_data_get = getattr(request_data, 'get', None)
    if raw_scope is None and callable(request_data_get):
        raw_scope = request_data_get('scope')
    scope = _normalize_budget_scope(raw_scope)
    if scope not in allowed_scopes:
        scope = 'my'
    scope_users = readable_users(user, scope)
    return scope, scope_users, choices


class BaseView:
    template_name = 'budget.html'


class BudgetContextMixin:
    """Mixin to provide user, months, and categories for budget views."""

    def get_budget_context(
        self,
    ) -> BudgetPageContextDict:
        request_obj = getattr(self, 'request', None)
        if request_obj is None:
            raise AttributeError('request attribute is required')
        request = cast('RequestWithContainer', request_obj)
        user = get_object_or_404(User, username=request.user)
        budget_scope, scope_users, budget_scope_choices = _resolve_budget_scope(
            user,
            request,
        )
        date_list_repository = request.container.budget.date_list_repository()
        dates = date_list_repository.filter(user__in=scope_users).values_list(
            'date',
            flat=True,
        )
        months = sorted({month.replace(day=1) for month in dates})
        expense_categories = list(
            get_categories(user, 'expense', users=scope_users),
        )
        income_categories = list(
            get_categories(user, 'income', users=scope_users),
        )
        return {
            'user': user,
            'months': months,
            'expense_categories': expense_categories,
            'income_categories': income_categories,
            'scope_users': scope_users,
            'budget_scope': budget_scope,
            'budget_scope_choices': budget_scope_choices,
            'analytics_currency': get_analytics_currency(request, scope_users),
        }


class BudgetView(
    LoginRequiredMixin,
    BudgetContextMixin,
    BaseView,
    ListView[Planning],
):
    model = Planning
    template_name = 'budget.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        budget_context = self.get_budget_context()
        request = cast('RequestWithContainer', self.request)
        budget_service = request.container.budget.budget_service()
        data = budget_service.aggregate_budget_data(
            user=budget_context['user'],
            months=budget_context['months'],
            expense_categories=budget_context['expense_categories'],
            income_categories=budget_context['income_categories'],
            currency=budget_context['analytics_currency'].currency,
            users=budget_context['scope_users'],
        )
        context.update(data)
        context.update(context['chart_data'])
        context.update(
            {
                'budget_scope': budget_context['budget_scope'],
                'budget_scope_choices': budget_context['budget_scope_choices'],
                'analytics_currency': budget_context['analytics_currency'],
            },
        )
        context.update(
            {
                'current_plan_expense': data['total_plan_expense'][-1]
                if data['total_plan_expense']
                else 0,
                'current_fact_expense': data['total_fact_expense'][-1]
                if data['total_fact_expense']
                else 0,
                'current_plan_income': data['total_plan_income'][-1]
                if data['total_plan_income']
                else 0,
                'current_fact_income': data['total_fact_income'][-1]
                if data['total_fact_income']
                else 0,
            },
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

    def get_template_names(self) -> list[str]:
        if self.request.headers.get('HX-Request'):
            return ['budget/partials/_budget_matrix.html']
        return [self.template_name]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        budget_context = self.get_budget_context()
        request = cast('RequestWithContainer', self.request)
        budget_service = request.container.budget.budget_service()
        data = budget_service.aggregate_expense_table(
            user=budget_context['user'],
            months=budget_context['months'],
            expense_categories=budget_context['expense_categories'],
            currency=budget_context['analytics_currency'].currency,
            users=budget_context['scope_users'],
        )
        context.update(data)
        context.update(
            build_budget_matrix_context(
                table_type='expense',
                months=data['months'],
                rows=data['expense_data'],
                total_fact=data['total_fact_expense'],
                total_plan=data['total_plan_expense'],
                selected_range=self.request.GET.get('range', '6'),
            ),
        )
        context.update(
            {
                'budget_scope': budget_context['budget_scope'],
                'budget_scope_choices': budget_context['budget_scope_choices'],
                'analytics_currency': budget_context['analytics_currency'],
            },
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

    def get_template_names(self) -> list[str]:
        if self.request.headers.get('HX-Request'):
            return ['budget/partials/_budget_matrix.html']
        return [self.template_name]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        budget_context = self.get_budget_context()
        request = cast('RequestWithContainer', self.request)
        budget_service = request.container.budget.budget_service()
        data = budget_service.aggregate_income_table(
            user=budget_context['user'],
            months=budget_context['months'],
            income_categories=budget_context['income_categories'],
            currency=budget_context['analytics_currency'].currency,
            users=budget_context['scope_users'],
        )
        context.update(data)
        context.update(
            build_budget_matrix_context(
                table_type='income',
                months=data['months'],
                rows=data['income_data'],
                total_fact=data['total_fact_income'],
                total_plan=data['total_plan_income'],
                selected_range=self.request.GET.get('range', '6'),
            ),
        )
        context.update(
            {
                'budget_scope': budget_context['budget_scope'],
                'budget_scope_choices': budget_context['budget_scope_choices'],
                'analytics_currency': budget_context['analytics_currency'],
            },
        )
        return context


class PlanningExpenseDict(TypedDict):
    category_id: int
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
                    'currency': {'type': 'string'},
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
        user = request.user
        request_with_container = cast('RequestWithContainer', request)
        _budget_scope, scope_users, _choices = _resolve_budget_scope(
            user,
            request,
        )
        date_list_repository = (
            request_with_container.container.budget.date_list_repository()
        )
        dates = date_list_repository.filter(user__in=scope_users).values_list(
            'date',
            flat=True,
        )
        months = sorted({month.replace(day=1) for month in dates})
        expense_categories = list(
            get_categories(user, 'expense', users=scope_users),
        )
        budget_service = (
            request_with_container.container.budget.budget_service()
        )
        currency = get_analytics_currency(request, scope_users).currency
        data = budget_service.aggregate_expense_api(
            user=user,
            months=months,
            expense_categories=expense_categories,
            currency=currency,
            users=scope_users,
        )
        return Response({**data, 'currency': currency})


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
                    'currency': {'type': 'string'},
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
        user = request.user
        request_with_container = cast('RequestWithContainer', request)
        _budget_scope, scope_users, _choices = _resolve_budget_scope(
            user,
            request,
        )
        date_list_repository = (
            request_with_container.container.budget.date_list_repository()
        )
        dates = date_list_repository.filter(user__in=scope_users).values_list(
            'date',
            flat=True,
        )
        months = sorted({month.replace(day=1) for month in dates})
        income_categories = list(
            get_categories(user, 'income', users=scope_users),
        )
        budget_service = (
            request_with_container.container.budget.budget_service()
        )
        currency = get_analytics_currency(request, scope_users).currency
        data = budget_service.aggregate_income_api(
            user=user,
            months=months,
            income_categories=income_categories,
            currency=currency,
            users=scope_users,
        )
        return Response({**data, 'currency': currency})
