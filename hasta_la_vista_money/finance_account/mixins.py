"""Mixin classes for finance account views.

This module provides reusable mixin classes that add functionality to views,
including group-based account filtering and user-specific data access.
"""

from typing import TYPE_CHECKING, cast

from django.db.models import QuerySet

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer


class GroupAccountMixin:
    """Mixin to provide group_id and accounts queryset for a user or group.

    Enables views to filter accounts by user groups, allowing for shared
    account access and group-based financial management.
    """

    def get_group_id(self) -> str | None:
        """Extract group_id from request parameters.

        Returns:
            The group ID from the request GET parameters, or None if
            not provided.
        """
        request_obj = getattr(self, 'request', None)
        if request_obj is None:
            raise AttributeError('request attribute is required')
        request = cast('RequestWithContainer', request_obj)
        return request.GET.get('group_id')

    def get_accounts(self, user: User) -> QuerySet[Account]:
        """Get accounts filtered by user or group.

        Args:
            user: The user whose accounts to retrieve.

        Returns:
            QuerySet of accounts filtered by user or group membership.
        """
        request_obj = getattr(self, 'request', None)
        if request_obj is None:
            raise AttributeError('request attribute is required')
        request = cast('RequestWithContainer', request_obj)
        group_id = self.get_group_id()
        account_service = request.container.core.account_service()
        result = account_service.get_accounts_for_user_or_group(user, group_id)
        return cast('QuerySet[Account, Account]', result)
