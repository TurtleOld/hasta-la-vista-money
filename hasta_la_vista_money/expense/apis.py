"""DRF API views for expense app."""

from typing import TYPE_CHECKING, Any, cast

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
)
from rest_framework.exceptions import APIException
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

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer


@extend_schema(
    tags=['expense'],
    summary='Получить расходы по группе',
    description='Получить список расходов для указанной группы пользователей',
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
        200: OpenApiResponse(description='HTML блок с расходами'),
        500: OpenApiResponse(description='Ошибка обработки'),
    },
)
class ExpenseByGroupAPIView(APIView, UserAuthMixin, FormErrorHandlingMixin):
    """API view для получения расходов по группе."""

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
        """Получить расходы по группе."""
        serializer = GroupQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        group_id = serializer.validated_data.get('group_id')

        request_with_container = cast('RequestWithContainer', request)

        expense_service = (
            request_with_container.container.expense.expense_service(
                user=request.user,
                request=request_with_container,
            )
        )

        try:
            all_expenses = expense_service.get_expenses_by_group(group_id)
            expense_data = [
                {
                    'id': expense.pk,
                    'amount': float(getattr(expense, 'amount', 0)),
                    'category': getattr(expense, 'category', {}).get('name', '')
                    if isinstance(getattr(expense, 'category', None), dict)
                    else getattr(getattr(expense, 'category', None), 'name', '')
                    if hasattr(getattr(expense, 'category', None), 'name')
                    else '',
                    'account': getattr(expense, 'account', {}).get('name', '')
                    if isinstance(getattr(expense, 'account', None), dict)
                    else getattr(
                        getattr(expense, 'account', None), 'name_account', ''
                    )
                    if hasattr(
                        getattr(expense, 'account', None), 'name_account'
                    )
                    else '',
                    'date': (
                        expense_date.strftime('%d.%m.%Y')
                        if (expense_date := getattr(expense, 'date', None))
                        is not None
                        and hasattr(expense_date, 'strftime')
                        else str(getattr(expense, 'date', ''))
                    ),
                }
                for expense in all_expenses
            ]

            paginator = self.pagination_class()
            paginated_data: list[dict[str, Any]] | None = (
                paginator.paginate_queryset(
                    expense_data,
                    request,  # type: ignore[arg-type]
                )
            )
            return paginator.get_paginated_response(paginated_data)
        except (ValueError, TypeError) as e:
            raise APIException(
                detail=f'Ошибка обработки данных: {e!s}',
                code='processing_error',
            ) from e


@extend_schema(
    tags=['expense'],
    summary='Получить данные расходов',
    description='Получить данные расходов в формате JSON для таблиц',
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
            description='Данные расходов',
            response={
                'type': 'object',
                'properties': {
                    'data': {
                        'type': 'array',
                        'items': {'type': 'object'},
                    },
                },
            },
        ),
        500: OpenApiResponse(description='Ошибка обработки'),
    },
)
class ExpenseDataAPIView(APIView, UserAuthMixin, FormErrorHandlingMixin):
    """API view для получения данных расходов."""

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
        """Получить данные расходов."""
        serializer = GroupQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        group_id = serializer.validated_data.get('group_id')

        request_with_container = cast('RequestWithContainer', request)

        expense_service = (
            request_with_container.container.expense.expense_service(
                user=request.user,
                request=request_with_container,
            )
        )

        try:
            all_data = expense_service.get_expense_data(group_id)
            paginator = self.pagination_class()
            paginated_data = paginator.paginate_queryset(all_data, request)
            return paginator.get_paginated_response(paginated_data)
        except (ValueError, TypeError) as e:
            raise APIException(
                detail=f'Ошибка обработки данных: {e!s}',
                code='processing_error',
            ) from e
