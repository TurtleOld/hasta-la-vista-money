"""DRF API views for budget app."""

from datetime import date
from datetime import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.utils import timezone
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import (
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from hasta_la_vista_money.api.serializers import BudgetTypeSerializer
from hasta_la_vista_money.authentication.authentication import (
    CookieJWTAuthentication,
)
from hasta_la_vista_money.core.mixins import (
    FormErrorHandlingMixin,
    UserAuthMixin,
)
from hasta_la_vista_money.expense.models import ExpenseCategory

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer
from hasta_la_vista_money.income.models import IncomeCategory
from hasta_la_vista_money.services.generate_dates import generate_date_list
from hasta_la_vista_money.users.models import User


@extend_schema(
    tags=['budget'],
    summary='Генерация списка дат',
    description='Генерирует список дат для бюджета на основе последней даты',
    request={
        'type': 'object',
        'properties': {
            'type': {
                'type': 'string',
                'enum': ['expense', 'income'],
                'description': 'Тип бюджета',
            },
        },
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
    authentication_classes = (CookieJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)

    def post(
        self,
        request: Request,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        """Generate date list.

        Args:
            request: HTTP request with budget type data (expense/income).
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            Response: JSON response with success flag and redirect_url.
        """
        serializer = BudgetTypeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        type_ = serializer.validated_data['type']

        user = cast('User', request.user)
        queryset_user = get_object_or_404(User, username=user)

        last_date_obj = queryset_user.budget_date_lists.last()
        if last_date_obj:
            queryset_last_date = timezone.make_aware(
                dt.combine(last_date_obj.date, dt.min.time()),
            )
        else:
            queryset_last_date = timezone.now().replace(day=1)
        generate_date_list(queryset_last_date, queryset_user, type_)

        if type_ == 'income':
            redirect_url = str(reverse_lazy('budget:income_table'))
        else:
            redirect_url = str(reverse_lazy('budget:expense_table'))

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
    authentication_classes = (CookieJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)

    def post(
        self,
        request: Request,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
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
    authentication_classes = (CookieJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)

    def post(
        self,
        request: Request,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
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

        if type_ == 'expense':
            expense_category = get_object_or_404(
                ExpenseCategory,
                id=request.data['category_id'],
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
                id=request.data['category_id'],
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

        return Response(
            {'success': True, 'amount': str(plan.amount)},
            status=status.HTTP_200_OK,
        )
