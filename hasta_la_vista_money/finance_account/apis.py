"""API views for finance account management.

This module provides REST API endpoints for creating and listing financial accounts,
with proper authentication and user-specific data filtering.
"""

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.serializers import AccountSerializer
from rest_framework.generics import ListCreateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle


class AccountListCreateAPIView(ListCreateAPIView):
    """API view for listing and creating financial accounts.

    Provides endpoints for:
    - GET: List all accounts belonging to the authenticated user
    - POST: Create a new account for the authenticated user

    Requires authentication and filters data by the current user.
    """

    serializer_class = AccountSerializer
    permission_classes = (IsAuthenticated,)
    throttle_classes = [UserRateThrottle]

    @property
    def queryset(self):
        """Return queryset filtered by the current user."""
        return Account.objects.filter(user=self.request.user)

    def list(self, request, *args, **kwargs):
        """List all accounts for the authenticated user."""
        queryset = self.get_queryset()
        serializer = AccountSerializer(queryset, many=True)
        return Response(serializer.data)
