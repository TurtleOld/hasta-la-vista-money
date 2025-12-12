"""DRF API views for income app."""

from typing import TYPE_CHECKING, Any, cast

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from hasta_la_vista_money.api.pagination import StandardResultsSetPagination
from hasta_la_vista_money.api.serializers import GroupQuerySerializer
from hasta_la_vista_money.core.mixins import (
    FormErrorHandlingMixin,
    UserAuthMixin,
)
from hasta_la_vista_money.income.models import Income

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer
    from hasta_la_vista_money.users.models import User


@extend_schema(
    tags=['income'],
    summary='Получить доходы по группе',
    description='Получить список доходов для указанной группы пользователей',
    parameters=[
        OpenApiParameter(
            name='group_id',
            type=str,
            location=OpenApiParameter.QUERY,
            description='ID группы (по умолчанию "my")',
            required=False,
        ),
    ],
    responses={
        200: OpenApiResponse(
            description='Данные доходов',
            response={
                'type': 'object',
                'properties': {
                    'incomes': {
                        'type': 'array',
                        'items': {'type': 'object'},
                    },
                },
            },
        ),
    },
)
class IncomeByGroupAPIView(APIView, UserAuthMixin, FormErrorHandlingMixin):
    """API view для получения доходов по группе."""

    schema = AutoSchema()
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)
    pagination_class = StandardResultsSetPagination

    def get(
        self,
        request: Request,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        """Получить доходы по группе."""
        serializer = GroupQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        group_id = serializer.validated_data.get('group_id')

        request_with_container = cast('RequestWithContainer', request)
        user = cast('User', request.user)

        account_service = (
            request_with_container.container.core.account_service()
        )
        users_in_group = account_service.get_users_for_group(user, group_id)

        if users_in_group:
            incomes = (
                Income.objects.filter(
                    user__in=users_in_group,
                )
                .select_related(
                    'user',
                    'category',
                    'account',
                )
                .order_by('-date')
            )
        else:
            incomes = Income.objects.none()

        income_data = [
            {
                'id': income.pk,
                'category_name': income.category.name,
                'account_name': income.account.name_account,
                'amount': float(income.amount),
                'date': income.date.strftime('%d.%m.%Y'),
                'user_name': income.user.username,
                'user_id': income.user.pk,
            }
            for income in incomes
        ]

        paginator = self.pagination_class()
        paginated_data: list[dict[str, object]] | None = (
            paginator.paginate_queryset(income_data, request)  # type: ignore[arg-type]
        )
        return paginator.get_paginated_response(paginated_data)


@extend_schema(
    tags=['income'],
    summary='Получить данные доходов',
    description='Получить данные доходов в формате JSON для таблиц',
    parameters=[
        OpenApiParameter(
            name='group_id',
            type=str,
            location=OpenApiParameter.QUERY,
            description='ID группы (по умолчанию "my")',
            required=False,
        ),
    ],
    responses={
        200: OpenApiResponse(
            description='Данные доходов',
            response={
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'integer'},
                        'category_name': {'type': 'string'},
                        'account_name': {'type': 'string'},
                        'amount': {'type': 'number'},
                        'date': {'type': 'string'},
                        'user_name': {'type': 'string'},
                        'user_id': {'type': 'integer'},
                    },
                },
            },
        ),
    },
)
class IncomeDataAPIView(APIView, UserAuthMixin, FormErrorHandlingMixin):
    """API view для получения данных доходов."""

    schema = AutoSchema()
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)
    pagination_class = StandardResultsSetPagination

    def get(
        self,
        request: Request,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        """Получить данные доходов."""
        serializer = GroupQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        group_id = serializer.validated_data.get('group_id', 'my')

        request_with_container = cast('RequestWithContainer', request)
        user = cast('User', request.user)

        account_service = (
            request_with_container.container.core.account_service()
        )
        users_in_group = account_service.get_users_for_group(user, group_id)

        if users_in_group:
            incomes = (
                Income.objects.filter(user__in=users_in_group)
                .select_related(
                    'category',
                    'account',
                    'user',
                )
                .order_by('-date')
            )
        else:
            incomes = Income.objects.none()

        data = [
            {
                'id': income.pk,
                'category_name': income.category.name,
                'account_name': income.account.name_account,
                'amount': float(income.amount),
                'date': income.date.strftime('%d.%m.%Y'),
                'user_name': income.user.username,
                'user_id': income.user.pk,
            }
            for income in incomes
        ]

        paginator = self.pagination_class()
        paginated_data: list[dict[str, object]] | None = (
            paginator.paginate_queryset(data, request)  # type: ignore[arg-type]
        )
        return paginator.get_paginated_response(paginated_data)


@extend_schema(
    tags=['income'],
    summary='Получить доход по ID',
    description='Получить детальную информацию о конкретном доходе',
    responses={
        200: OpenApiResponse(
            description='Данные дохода',
            response={
                'type': 'object',
                'properties': {
                    'id': {'type': 'integer'},
                    'category_name': {'type': 'string'},
                    'account_name': {'type': 'string'},
                    'amount': {'type': 'number'},
                    'date': {'type': 'string'},
                    'user_name': {'type': 'string'},
                    'user_id': {'type': 'integer'},
                },
            },
        ),
        404: OpenApiResponse(description='Доход не найден'),
    },
)
class IncomeRetrieveAPIView(RetrieveAPIView[Income], UserAuthMixin):
    """API view для получения конкретного дохода."""

    schema = AutoSchema()
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)
    queryset = Income.objects.select_related('category', 'account', 'user')

    def retrieve(
        self,
        request: Request,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        """Получить доход по ID."""
        income = self.get_object()
        data = {
            'id': income.pk,
            'category_name': income.category.name,
            'account_name': income.account.name_account,
            'amount': float(income.amount),
            'date': income.date.strftime('%d.%m.%Y'),
            'user_name': income.user.username,
            'user_id': income.user.pk,
        }
        return Response(data, status=status.HTTP_200_OK)
