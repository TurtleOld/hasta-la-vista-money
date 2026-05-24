"""DRF API views for the unified transactions app.

Mirrors the historical income / expense API surface but is discriminated
by a ``?type=`` query parameter, with the default returning all
transactions for the user.
"""

from typing import TYPE_CHECKING, Any, cast

from django.utils.dateparse import parse_date
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
from hasta_la_vista_money.authentication.authentication import (
    CookieJWTAuthentication,
)
from hasta_la_vista_money.core.mixins import (
    FormErrorHandlingMixin,
    UserAuthMixin,
)
from hasta_la_vista_money.transactions.models import (
    Transaction,
    TransactionType,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer
    from hasta_la_vista_money.users.models import User


TYPE_QUERY_PARAM = OpenApiParameter(
    name='type',
    type=str,
    location=OpenApiParameter.QUERY,
    description='Тип операции: income | expense (по умолчанию — все)',
    required=False,
    enum=[choice for choice, _ in TransactionType.choices],
)

GROUP_QUERY_PARAM = OpenApiParameter(
    name='group_id',
    type=str,
    location=OpenApiParameter.QUERY,
    description='ID группы (по умолчанию "my")',
    required=False,
)


def _filter_by_type(queryset: Any, request: Request) -> Any:
    """Apply ``?type=`` filtering to a Transaction queryset."""
    type_value = request.query_params.get('type')
    if type_value:
        return queryset.filter(type=type_value)
    return queryset


def _serialize(transaction_obj: Transaction) -> dict[str, Any]:
    """Convert a Transaction instance to its JSON shape."""
    return {
        'id': transaction_obj.pk,
        'type': transaction_obj.type,
        'category_name': transaction_obj.category.name,
        'account_name': transaction_obj.account.name_account,
        'amount': float(transaction_obj.amount),
        'date': transaction_obj.date.strftime('%d.%m.%Y'),
        'user_name': transaction_obj.user.username,
        'user_id': transaction_obj.user.pk,
    }


@extend_schema(
    tags=['transactions'],
    summary='Получить операции по группе',
    description=(
        'Получить список операций (доходов и/или расходов) для указанной '
        'группы пользователей.'
    ),
    parameters=[GROUP_QUERY_PARAM, TYPE_QUERY_PARAM],
    responses={
        200: OpenApiResponse(
            description='Данные операций',
            response={
                'type': 'object',
                'properties': {
                    'results': {
                        'type': 'array',
                        'items': {'type': 'object'},
                    },
                },
            },
        ),
    },
)
class TransactionByGroupAPIView(APIView, UserAuthMixin, FormErrorHandlingMixin):
    """API view for retrieving transactions by group."""

    schema = AutoSchema()
    authentication_classes = (CookieJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)
    pagination_class = StandardResultsSetPagination

    def get(
        self,
        request: Request,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        """Return paginated transactions for the requested group."""
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
            transactions = (
                Transaction.objects.filter(user__in=users_in_group)
                .select_related('user', 'category', 'account')
                .order_by('-date')
            )
            transactions = _filter_by_type(transactions, request)
        else:
            transactions = Transaction.objects.none()

        data = [_serialize(transaction_obj) for transaction_obj in transactions]
        paginator = self.pagination_class()
        paginated_data: list[dict[str, object]] | None = (
            paginator.paginate_queryset(data, request)  # type: ignore[arg-type]
        )
        return paginator.get_paginated_response(paginated_data)


@extend_schema(
    tags=['transactions'],
    summary='Получить данные операций',
    description='Получить данные операций в формате JSON для таблиц.',
    parameters=[GROUP_QUERY_PARAM, TYPE_QUERY_PARAM],
    responses={
        200: OpenApiResponse(
            description='Данные операций',
            response={
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'integer'},
                        'type': {'type': 'string'},
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
class TransactionDataAPIView(APIView, UserAuthMixin, FormErrorHandlingMixin):
    """API view for retrieving transaction data for table widgets."""

    schema = AutoSchema()
    authentication_classes = (CookieJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)
    pagination_class = StandardResultsSetPagination

    def get(
        self,
        request: Request,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        """Return paginated transaction data with optional date filters."""
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
            transactions = (
                Transaction.objects.filter(user__in=users_in_group)
                .select_related('category', 'account', 'user')
                .order_by('-date')
            )
            transactions = _filter_by_type(transactions, request)
            date_after = parse_date(request.query_params.get('date_after', ''))
            date_before = parse_date(
                request.query_params.get('date_before', ''),
            )
            if date_after is not None:
                transactions = transactions.filter(date__date__gte=date_after)
            if date_before is not None:
                transactions = transactions.filter(date__date__lte=date_before)
        else:
            transactions = Transaction.objects.none()

        data = [_serialize(transaction_obj) for transaction_obj in transactions]
        paginator = self.pagination_class()
        paginated_data: list[dict[str, object]] | None = (
            paginator.paginate_queryset(data, request)
        )
        return paginator.get_paginated_response(paginated_data)


@extend_schema(
    tags=['transactions'],
    summary='Получить операцию по ID',
    description='Получить детальную информацию о конкретной операции.',
    responses={
        200: OpenApiResponse(
            description='Данные операции',
            response={
                'type': 'object',
                'properties': {
                    'id': {'type': 'integer'},
                    'type': {'type': 'string'},
                    'category_name': {'type': 'string'},
                    'account_name': {'type': 'string'},
                    'amount': {'type': 'number'},
                    'date': {'type': 'string'},
                    'user_name': {'type': 'string'},
                    'user_id': {'type': 'integer'},
                },
            },
        ),
        404: OpenApiResponse(description='Операция не найдена'),
    },
)
class TransactionRetrieveAPIView(
    RetrieveAPIView[Transaction],
    UserAuthMixin,
):
    """API view for retrieving a single transaction by primary key."""

    schema = AutoSchema()
    authentication_classes = (CookieJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)
    queryset = Transaction.objects.select_related('category', 'account', 'user')

    def retrieve(
        self,
        request: Request,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        """Return the transaction with the requested primary key."""
        transaction_obj = self.get_object()
        return Response(_serialize(transaction_obj), status=status.HTTP_200_OK)
