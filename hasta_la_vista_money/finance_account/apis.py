"""API views for finance account management.

This module provides REST API endpoints for creating and listing
financial accounts,
with proper authentication and user-specific data filtering.
"""

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import extend_schema
from rest_framework.generics import ListCreateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import UserRateThrottle

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.serializers import AccountSerializer


@extend_schema(
    tags=['finance_account'],
    summary='Список и создание счетов',
    description=(
        'Получить список всех счетов текущего пользователя '
        'или создать новый счет'
    ),
)
class AccountListCreateAPIView(ListCreateAPIView):
    """API view for listing and creating financial accounts.

    Provides endpoints for:
    - GET: List all accounts belonging to the authenticated user
    - POST: Create a new account for the authenticated user

    Requires authentication and filters data by the current user.
    """

    schema = AutoSchema()
    serializer_class = AccountSerializer
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)

    def get_queryset(self):
        """Return queryset filtered by the current user."""
        if getattr(self, 'swagger_fake_view', False):
            return Account.objects.none()
        return Account.objects.filter(user=self.request.user)
