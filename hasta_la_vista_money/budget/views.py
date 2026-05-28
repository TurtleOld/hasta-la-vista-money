from datetime import date
from datetime import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TypedDict, cast

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
from hasta_la_vista_money.budget.presentation import build_budget_matrix_context
from hasta_la_vista_money.budget.repositories import (
    PlanningRepository,
)
from hasta_la_vista_money.budget.services.budget import (
    get_categories,
)
from hasta_la_vista_money.services.generate_dates import generate_date_list
from hasta_la_vista_money.transactions.models import Category
from hasta_la_vista_money.transactions.repositories import TransactionRepository
from hasta_la_vista_money.users.models import FamilyGroupMembership, User
from hasta_la_vista_money.users.services.groups import get_family_groups

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


def _normalize_budget_scope(value: str | None) -> str:
    if value == 'family':
        return 'family'
    return 'my'


def _owned_family_group_ids(user: User) -> list[int]:
    return list(
        FamilyGroupMembership.objects.filter(
            user=user,
            role=FamilyGroupMembership.Role.OWNER,
        ).values_list('group_id', flat=True),
    )


def _family_users_for_budget(user: User) -> list[User]:
    group_ids = _owned_family_group_ids(user)
    if not group_ids:
        return [user]
    return list(
        User.objects.filter(family_memberships__group_id__in=group_ids)
        .distinct()
        .order_by('username'),
    ) or [user]


def _scope_choices(
    user: User,
    request: Any,
) -> list[BudgetScopeChoiceDict]:
    family_groups = get_family_groups(user, request)
    has_owned_family = any(
        group['role'] == FamilyGroupMembership.Role.OWNER
        for group in family_groups
    )
    choices: list[BudgetScopeChoiceDict] = [
        {'value': 'my', 'label': 'Мой бюджет'},
    ]
    if has_owned_family:
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
    scope_users = (
        _family_users_for_budget(user) if scope == 'family' else [user]
    )
    return scope, scope_users, choices


def get_fact_amount(
    user: User,
    category: Category,
    month: date,
    type_: str,
    transaction_repository: TransactionRepository | None = None,
) -> Decimal | int:
    """Return the total transaction amount for a category in a given month."""
    if transaction_repository is None:
        raise ValueError('transaction_repository must be provided')

    qs = transaction_repository.filter_by_user_category_and_month(
        user,
        category,
        month,
    ).filter(type=type_)
    return qs.aggregate(total=Sum('amount'))['total'] or 0


def get_plan_amount(
    user: User,
    category: Category,
    month: date,
    type_: str,
    planning_repository: PlanningRepository | None = None,
) -> Decimal | int:
    """Return the planned amount for a category in a given month."""
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
            users=budget_context['scope_users'],
        )
        context.update(data)
        context.update(context['chart_data'])
        context.update(
            {
                'budget_scope': budget_context['budget_scope'],
                'budget_scope_choices': budget_context['budget_scope_choices'],
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
            },
        )
        return context


class GenerateDateView(LoginRequiredMixin, View):
    """View for generating date list for both expense and income types."""

    def post(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        """Generate date list for both expense and income types."""
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
        data = budget_service.aggregate_expense_api(
            user=user,
            months=months,
            expense_categories=expense_categories,
            users=scope_users,
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
        data = budget_service.aggregate_income_api(
            user=user,
            months=months,
            income_categories=income_categories,
            users=scope_users,
        )
        return Response(data)
