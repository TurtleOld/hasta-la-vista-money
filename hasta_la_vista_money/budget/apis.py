"""DRF API views for budget app."""

from datetime import date
from datetime import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.utils import timezone
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import (
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from hasta_la_vista_money import constants
from hasta_la_vista_money.authentication.authentication import (
    CookieJWTAuthentication,
)
from hasta_la_vista_money.budget.presentation import build_budget_matrix_context
from hasta_la_vista_money.budget.services.budget import get_categories
from hasta_la_vista_money.budget.views import _resolve_budget_scope
from hasta_la_vista_money.core.mixins import (
    FormErrorHandlingMixin,
    UserAuthMixin,
)
from hasta_la_vista_money.services.generate_dates import generate_date_list
from hasta_la_vista_money.transactions.models import Category, TransactionType
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer


def _is_htmx_request(request: Request) -> bool:
    return request.headers.get('HX-Request') == 'true'


def _budget_range_from_request(request: Request) -> str:
    range_value = request.query_params.get('range')
    if range_value is None:
        range_value = request.data.get('range')
    return str(range_value or '6')


def _render_budget_matrix(request: Request, table_type: str) -> Any:
    request_with_container = cast('RequestWithContainer', request)
    user = cast('User', request.user)
    budget_scope, scope_users, budget_scope_choices = _resolve_budget_scope(
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
    budget_service = request_with_container.container.budget.budget_service()

    if table_type == TransactionType.EXPENSE:
        categories = list(
            get_categories(user, TransactionType.EXPENSE, users=scope_users),
        )
        data = budget_service.aggregate_expense_table(
            user=user,
            months=months,
            expense_categories=categories,
            users=scope_users,
        )
        context = build_budget_matrix_context(
            table_type=TransactionType.EXPENSE,
            months=data['months'],
            rows=data['expense_data'],
            total_fact=data['total_fact_expense'],
            total_plan=data['total_plan_expense'],
            selected_range=_budget_range_from_request(request),
        )
    else:
        categories = list(
            get_categories(user, TransactionType.INCOME, users=scope_users),
        )
        data = budget_service.aggregate_income_table(
            user=user,
            months=months,
            income_categories=categories,
            users=scope_users,
        )
        context = build_budget_matrix_context(
            table_type=TransactionType.INCOME,
            months=data['months'],
            rows=data['income_data'],
            total_fact=data['total_fact_income'],
            total_plan=data['total_plan_income'],
            selected_range=_budget_range_from_request(request),
        )

    context.update(
        {
            'budget_scope': budget_scope,
            'budget_scope_choices': budget_scope_choices,
        },
    )
    return render(request, 'budget/partials/_budget_matrix.html', context)


def _render_budget_limits(request: Request) -> Any:
    request_with_container = cast('RequestWithContainer', request)
    user = cast('User', request.user)
    budget_scope, scope_users, budget_scope_choices = _resolve_budget_scope(
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
        get_categories(user, TransactionType.EXPENSE, users=scope_users),
    )
    budget_service = request_with_container.container.budget.budget_service()
    context = {
        'budget_limit_overview': budget_service.aggregate_budget_limit_overview(
            user=user,
            months=months,
            expense_categories=expense_categories,
            users=scope_users,
        ),
        'budget_scope': budget_scope,
        'budget_scope_choices': budget_scope_choices,
    }
    return render(request, 'budget/partials/_budget_limits.html', context)


@extend_schema(
    tags=['budget'],
    summary='Генерация списка дат',
    description='Генерирует список дат для бюджета на основе последней даты',
    request={
        'type': 'object',
        'properties': {},
    },
    responses={
        200: OpenApiResponse(
            description='Успешная генерация дат',
            response={
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                    'redirect_url': {'type': 'string'},
                },
            },
        ),
    },
)
class GenerateDatesAPIView(APIView, UserAuthMixin, FormErrorHandlingMixin):
    """API view for generating date list.

    Provides an endpoint to generate a list of dates for budgeting
    based on the user's last date.
    """

    schema = AutoSchema()
    authentication_classes = (CookieJWTAuthentication, SessionAuthentication)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)

    def post(
        self,
        request: Request,
        *args: Any,
        **kwargs: Any,
    ) -> Response | Any:
        """Generate date list.

        Args:
            request: HTTP request.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            Response: JSON response with success flag and redirect_url.
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

        # Generate dates for both income and expense types
        generate_date_list(queryset_last_date, queryset_user, 'expense')
        generate_date_list(queryset_last_date, queryset_user, 'income')

        redirect_url = str(reverse_lazy('budget:list'))

        if _is_htmx_request(request):
            response = Response({'success': True}, status=status.HTTP_200_OK)
            response['HX-Redirect'] = redirect_url
            return response

        return Response(
            {'success': True, 'redirect_url': redirect_url},
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=['budget'],
    summary='Изменить планирование',
    description='Изменяет значение планирования (временная операция)',
    request={
        'type': 'object',
        'properties': {
            'planning': {
                'type': 'string',
                'description': 'Значение планирования',
            },
        },
    },
    responses={
        200: OpenApiResponse(
            description='Значение планирования',
            response={
                'type': 'object',
                'properties': {
                    'planning_value': {'type': 'string'},
                },
            },
        ),
        400: OpenApiResponse(description='Ошибка парсинга JSON'),
    },
)
class ChangePlanningAPIView(APIView, UserAuthMixin, FormErrorHandlingMixin):
    """API view for changing planning amounts.

    Provides a temporary endpoint for changing planning values
    (used for intermediate operations).
    """

    schema = AutoSchema()
    authentication_classes = (CookieJWTAuthentication, SessionAuthentication)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)

    def post(
        self,
        request: Request,
        *args: Any,
        **kwargs: Any,
    ) -> Response | Any:
        """Change planning.

        Args:
            request: HTTP request with planning data.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            Response: JSON response with planning_value.

        Raises:
            ValidationError: When data parsing error occurs.
        """
        try:
            planning_value = request.data.get('planning')
            return Response(
                {'planning_value': planning_value},
                status=status.HTTP_200_OK,
            )
        except (ValueError, TypeError) as e:
            raise ValidationError(
                detail=f'Data parsing error: {e!s}',
                code='parse_error',
            ) from e


@extend_schema(
    tags=['budget'],
    summary='Сохранить планирование',
    description='Сохраняет план по категории, месяцу и типу (расход/доход)',
    request={
        'type': 'object',
        'properties': {
            'month': {
                'type': 'string',
                'format': 'date',
                'description': 'Месяц планирования (ISO format)',
            },
            'amount': {
                'type': 'number',
                'description': 'Сумма планирования',
            },
            'type': {
                'type': 'string',
                'enum': ['expense', 'income'],
                'description': 'Тип планирования',
            },
            'category_id': {
                'type': 'integer',
                'description': 'ID категории',
            },
        },
        'required': ['month', 'amount', 'type', 'category_id'],
    },
    responses={
        200: OpenApiResponse(
            description='Планирование успешно сохранено',
            response={
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                    'amount': {'type': 'string'},
                },
            },
        ),
        400: OpenApiResponse(description='Неверные данные запроса'),
    },
)
class SavePlanningAPIView(APIView, UserAuthMixin, FormErrorHandlingMixin):
    """API view for saving planning.

    Provides an endpoint to save a plan by category, month,
    and type (expense/income).
    """

    schema = AutoSchema()
    authentication_classes = (CookieJWTAuthentication, SessionAuthentication)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)

    def post(
        self,
        request: Request,
        *args: Any,
        **kwargs: Any,
    ) -> Response | Any:
        """Save planning.

        Args:
            request: HTTP request with planning data (month, amount,
                type, category_id).
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            Response: JSON response with success flag and saved amount.

        Raises:
            ValidationError: When request data format is invalid.
        """
        request_with_container = cast('RequestWithContainer', request)
        user = cast('User', request.user)
        budget_scope, scope_users, _choices = _resolve_budget_scope(
            user,
            request,
        )

        try:
            month = date.fromisoformat(request.data['month'])
        except (ValueError, KeyError) as e:
            raise ValidationError(
                detail='Invalid month format. Expected ISO format (YYYY-MM-DD)',
                code='invalid_month_format',
            ) from e

        try:
            amount = Decimal(str(request.data['amount']))
        except (ValueError, TypeError, KeyError):
            amount = Decimal(0)

        type_ = request.data.get('type')
        planning_repository = (
            request_with_container.container.budget.planning_repository()
        )

        category_lookup: dict[str, Any] = {
            'id': request.data['category_id'],
            'type': type_,
        }
        if budget_scope == 'family':
            category_lookup['user__in'] = scope_users
        else:
            category_lookup['user'] = user
        category = get_object_or_404(Category, **category_lookup)
        planning_user = category.user if budget_scope == 'family' else user
        plan, created = planning_repository.get_or_create_planning(
            user=planning_user,
            category=category,
            date=month,
            planning_type=type_,
            defaults={'amount': amount},
        )

        if not created:
            plan.amount = Decimal(str(amount))
            plan.save()

        if _is_htmx_request(request):
            return _render_budget_matrix(request, str(type_))

        return Response(
            {'success': True, 'amount': str(plan.amount)},
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=['budget'],
    summary='Сохранить бюджетный лимит',
    description=(
        'Сохраняет месячный лимит расходов для категории или всего бюджета'
    ),
    request={
        'type': 'object',
        'properties': {
            'month': {'type': 'string', 'format': 'date'},
            'amount_limit': {'type': 'number'},
            'alert_threshold': {'type': 'integer'},
            'category_id': {'type': 'integer', 'nullable': True},
        },
        'required': ['month', 'amount_limit'],
    },
    responses={
        200: OpenApiResponse(
            description='Бюджетный лимит сохранён',
            response={
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                    'amount_limit': {'type': 'string'},
                },
            },
        ),
        400: OpenApiResponse(description='Неверные данные запроса'),
    },
)
class SaveBudgetLimitAPIView(APIView, UserAuthMixin, FormErrorHandlingMixin):
    """API view for saving monthly expense budget limits."""

    schema = AutoSchema()
    authentication_classes = (CookieJWTAuthentication, SessionAuthentication)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)

    def post(
        self,
        request: Request,
        *args: Any,
        **kwargs: Any,
    ) -> Response | Any:
        request_with_container = cast('RequestWithContainer', request)
        user = cast('User', request.user)
        budget_scope, scope_users, _choices = _resolve_budget_scope(
            user,
            request,
        )

        try:
            month = date.fromisoformat(request.data['month']).replace(day=1)
        except (ValueError, KeyError) as e:
            raise ValidationError(
                detail='Invalid month format. Expected ISO format (YYYY-MM-DD)',
                code='invalid_month_format',
            ) from e

        try:
            amount_limit = Decimal(str(request.data['amount_limit']))
        except (ValueError, TypeError, KeyError) as e:
            raise ValidationError(
                detail='Invalid amount_limit value',
                code='invalid_amount_limit',
            ) from e

        if amount_limit < 0:
            raise ValidationError(
                detail='amount_limit must be greater than or equal to zero',
                code='invalid_amount_limit',
            )

        try:
            alert_threshold = int(request.data.get('alert_threshold') or 80)
        except (TypeError, ValueError) as e:
            raise ValidationError(
                detail='Invalid alert_threshold value',
                code='invalid_alert_threshold',
            ) from e

        if (
            alert_threshold < constants.ONE
            or alert_threshold > constants.ONE_HUNDRED
        ):
            raise ValidationError(
                detail='alert_threshold must be between 1 and 100',
                code='invalid_alert_threshold',
            )

        raw_category_id = request.data.get('category_id')
        category = None
        budget_user = user
        if raw_category_id:
            category_lookup = {
                'id': raw_category_id,
                'type': TransactionType.EXPENSE,
            }
            if budget_scope == 'family':
                category_lookup['user__in'] = scope_users
            else:
                category_lookup['user'] = user
            category = get_object_or_404(Category, **category_lookup)
            budget_user = category.user

        budget_repository = (
            request_with_container.container.budget.budget_repository()
        )
        budget, created = budget_repository.get_or_create_budget(
            user=budget_user,
            period=month,
            category=category,
            defaults={
                'amount_limit': amount_limit,
                'alert_threshold': alert_threshold,
            },
        )
        if not created:
            budget.amount_limit = amount_limit
            budget.alert_threshold = alert_threshold
            budget.save()

        if _is_htmx_request(request):
            return _render_budget_limits(request)

        return Response(
            {'success': True, 'amount_limit': str(budget.amount_limit)},
            status=status.HTTP_200_OK,
        )
