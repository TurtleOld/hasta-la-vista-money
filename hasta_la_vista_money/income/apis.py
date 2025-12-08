"""DRF API views for income app."""

from typing import Any, cast

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
from rest_framework.views import APIView

from hasta_la_vista_money.core.mixins import FormErrorHandlingMixin, UserAuthMixin
from hasta_la_vista_money.core.types import RequestWithContainer
from hasta_la_vista_money.income.models import Income
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

    def get(
        self,
        request: Request,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        """Получить доходы по группе."""
        request_with_container = cast('RequestWithContainer', request)
        group_id = request.query_params.get('group_id')
        user = cast('User', request.user)

        account_service = request_with_container.container.core.account_service()
        users_in_group = account_service.get_users_for_group(user, group_id)

        if users_in_group:
            incomes = Income.objects.filter(
                user__in=users_in_group,
            ).select_related(
                'user',
                'category',
                'account',
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

        return Response({'incomes': income_data}, status=status.HTTP_200_OK)


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

    def get(
        self,
        request: Request,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        """Получить данные доходов."""
        request_with_container = cast('RequestWithContainer', request)
        group_id = request.query_params.get('group_id', 'my')
        user = cast('User', request.user)

        account_service = request_with_container.container.core.account_service()
        users_in_group = account_service.get_users_for_group(user, group_id)

        if users_in_group:
            incomes = (
                Income.objects.filter(user__in=users_in_group)
                .select_related(
                    'category',
                    'account',
                    'user',
                )
                .all()
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

        return Response(data, status=status.HTTP_200_OK)


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

