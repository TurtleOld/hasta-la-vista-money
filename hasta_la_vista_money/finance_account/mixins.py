"""Mixin classes for finance account views.

This module provides reusable mixin classes that add functionality to views,
including group-based account filtering and user-specific data access.
"""

from typing import cast

from django.db.models import QuerySet
from django.http import HttpRequest

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import User


class GroupAccountMixin:
    """Mixin to provide group_id and accounts queryset for a user or group.

    Enables views to filter accounts by user groups, allowing for shared
    account access and group-based financial management.
    """

    request: HttpRequest

    def get_group_id(self) -> str | None:
        """Extract group_id from request parameters.

        Returns:
            The group ID from the request GET parameters, or None if
            not provided.
        """
        return self.request.GET.get('group_id')

    def get_accounts(self, user: User) -> QuerySet[Account]:
        """Get accounts filtered by user or group.

        Args:
            user: The user whose accounts to retrieve.

        Returns:
            QuerySet of accounts filtered by user or group membership.
        """
        group_id = self.get_group_id()
        container = getattr(self.request, 'container', None)
        if container is None:
            container = ApplicationContainer()
        account_service = container.core.account_service()
        result = account_service.get_accounts_for_user_or_group(user, group_id)
        return cast('QuerySet[Account, Account]', result)
