"""API views for finance account management.

This module provides REST API endpoints for creating and listing
financial accounts,
with proper authentication and user-specific data filtering.
"""

from typing import TYPE_CHECKING, Any, cast

from django.db.models import QuerySet
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
)
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
)
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
from hasta_la_vista_money.finance_account.models import Account

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer
from hasta_la_vista_money.finance_account.serializers import AccountSerializer

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User


@extend_schema(
    tags=['finance_account'],
    summary='Список и создание счетов',
    description=(
        'Получить список всех счетов текущего пользователя '
        'или создать новый счет'
    ),
)
class AccountListCreateAPIView(ListCreateAPIView[Account]):
    """API view for listing and creating financial accounts.

    Provides endpoints for:
    - GET: List all accounts belonging to the authenticated user
    - POST: Create a new account for the authenticated user

    Requires authentication and filters data by the current user.
    """

    schema = AutoSchema()
    serializer_class = AccountSerializer
    authentication_classes = (CookieJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)
    pagination_class = StandardResultsSetPagination

    def get_queryset(self) -> QuerySet[Account, Account]:
        """Return queryset filtered by the current user.

        Returns:
            QuerySet[Account, Account]: QuerySet of accounts belonging to
                the authenticated user, ordered by ID descending.
        """
        if getattr(self, 'swagger_fake_view', False):
            return Account.objects.none()
        user = cast('User', self.request.user)
        return Account.objects.filter(user=user).order_by('-id')


@extend_schema(
    tags=['finance_account'],
    summary='Получить счета по группе',
    description='Получить список счетов для указанной группы пользователей',
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
            description='Список счетов',
            response={
                'type': 'object',
                'properties': {
                    'accounts': {
                        'type': 'array',
                        'items': {'$ref': '#/components/schemas/Account'},
                    },
                },
            },
        ),
    },
)
class AccountsByGroupAPIView(APIView, UserAuthMixin, FormErrorHandlingMixin):
    """API view for retrieving accounts by group.

    Provides an endpoint to get a list of accounts filtered by user group.
    """

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
        """Get accounts by group.

        Args:
            request: HTTP request with group_id query parameter.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            Response: Paginated list of accounts in JSON format.
        """
        serializer = GroupQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        group_id = serializer.validated_data.get('group_id')

        request_with_container = cast('RequestWithContainer', request)
        user = cast('User', request.user)

        account_service = (
            request_with_container.container.core.account_service()
        )
        accounts = account_service.get_accounts_for_user_or_group(
            user,
            group_id,
        )

        if hasattr(accounts, 'select_related'):
            accounts = accounts.select_related('user').order_by('-id')

        paginator = self.pagination_class()
        paginated_queryset = paginator.paginate_queryset(
            accounts,
            request,  # type: ignore[arg-type]
        )
        account_serializer = AccountSerializer(
            paginated_queryset,
            many=True,
            context={'request': request},
        )
        return paginator.get_paginated_response(account_serializer.data)


@extend_schema(
    tags=['finance_account'],
    summary='Получить, обновить или удалить счет',
    description=(
        'Получить, обновить или удалить счет по ID. '
        'Доступно только для счетов текущего пользователя.'
    ),
)
class AccountRetrieveUpdateDestroyAPIView(
    RetrieveUpdateDestroyAPIView[Account],
):
    """API view for retrieving, updating, and deleting a single account.

    Provides endpoints for:
    - GET: Retrieve a single account by ID
    - PATCH/PUT: Update a single account by ID
    - DELETE: Delete a single account by ID

    Requires authentication and ensures users can only access
    their own accounts.
    """

    schema = AutoSchema()
    serializer_class = AccountSerializer
    authentication_classes = (CookieJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)

    def get_queryset(self) -> QuerySet[Account, Account]:
        """Return queryset filtered by the current user.

        Returns:
            QuerySet[Account, Account]: QuerySet of accounts belonging to
                the authenticated user, ordered by ID descending.
        """
        if getattr(self, 'swagger_fake_view', False):
            return Account.objects.none()
        user = cast('User', self.request.user)
        return Account.objects.filter(user=user).order_by('-id')
