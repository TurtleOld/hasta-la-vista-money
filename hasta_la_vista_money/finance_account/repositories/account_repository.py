"""Django repository for Account model.

This module provides data access layer for Account model,
including filtering by user, group, type, and currency.
"""

from django.db.models import QuerySet

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import User


class AccountRepository:
    """Repository for Account model operations.

    Provides methods for accessing and manipulating account data,
    including filtering by user, group, type, and currency.
    """

    def get_by_id(self, account_id: int) -> Account:
        """Get account by ID.

        Args:
            account_id: ID of the account to retrieve.

        Returns:
            Account: Account instance.

        Raises:
            Account.DoesNotExist: If account with given ID doesn't exist.
        """
        return Account.objects.get(pk=account_id)

    def get_by_id_and_user(
        self,
        account_id: int,
        user: User,
    ) -> Account | None:
        """Get account by ID and user.

        Args:
            account_id: ID of the account to retrieve.
            user: User instance to filter by.

        Returns:
            Account | None: Account instance if found, None otherwise.
        """
        try:
            return Account.objects.get(id=account_id, user=user)
        except Account.DoesNotExist:
            return None

    def get_by_user(self, user: User) -> QuerySet[Account]:
        """Get all accounts for a user.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[Account]: QuerySet of user's accounts.
        """
        return Account.objects.by_user(user)

    def get_by_user_with_related(self, user: User) -> QuerySet[Account]:
        """Get all accounts for a user with user relation optimized.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[Account]: QuerySet with select_related('user')
                optimization.
        """
        return Account.objects.by_user_with_related(user)

    def get_by_user_and_group(
        self,
        user: User,
        group_id: str | None = None,
    ) -> QuerySet[Account]:
        """Get accounts for user or group.

        Group ID parameter semantics:
        - 'my': only user's own accounts
        - None: all available accounts (own + from all user's groups)
        - '123' (group ID): accounts of all users from specified group

        Args:
            user: User instance to filter by.
            group_id: Group ID or 'my' for filtering, None for all available.

        Returns:
            QuerySet[Account]: QuerySet of accounts according to filter.
        """
        if group_id == 'my':
            return Account.objects.filter(user=user).select_related('user')

        if group_id is None:
            user_with_groups = User.objects.prefetch_related('groups').get(
                pk=user.pk,
            )
            user_groups = user_with_groups.groups.all()
            if user_groups.exists():
                users_in_groups = User.objects.filter(
                    groups__in=user_groups,
                ).distinct()
                return (
                    Account.objects.filter(user__in=users_in_groups)
                    .select_related('user')
                    .distinct()
                )
            return Account.objects.filter(user=user).select_related('user')

        users_in_group = User.objects.filter(groups__id=group_id).distinct()
        if users_in_group.exists():
            return (
                Account.objects.filter(user__in=users_in_group)
                .select_related('user')
                .distinct()
            )
        return Account.objects.filter(user=user).select_related('user')

    def get_credit_accounts(self) -> QuerySet[Account]:
        """Get only credit accounts and credit cards.

        Returns:
            QuerySet[Account]: QuerySet filtered to credit accounts only.
        """
        return Account.objects.credit()

    def get_debit_accounts(self) -> QuerySet[Account]:
        """Get only debit accounts, debit cards, and cash.

        Returns:
            QuerySet[Account]: QuerySet filtered to debit accounts only.
        """
        return Account.objects.debit()

    def get_by_currency(self, currency: str) -> QuerySet[Account]:
        """Get accounts by currency code.

        Args:
            currency: Currency code (e.g., 'RUB', 'USD').

        Returns:
            QuerySet[Account]: QuerySet filtered by currency.
        """
        return Account.objects.by_currency(currency)

    def get_by_type(self, type_account: str) -> QuerySet[Account]:
        """Get accounts by account type.

        Args:
            type_account: Account type (e.g., 'CreditCard', 'DebitCard').

        Returns:
            QuerySet[Account]: QuerySet filtered by account type.
        """
        return Account.objects.by_type(type_account)

    def create_account(self, **kwargs: object) -> Account:
        """Create a new account.

        Args:
            **kwargs: Account field values (
                user, name_account, type_account, etc.).

        Returns:
            Account: Created account instance.
        """
        return Account.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[Account]:
        """Filter accounts by given criteria.

        Args:
            **kwargs: Filter criteria (field=value pairs).

        Returns:
            QuerySet[Account]: Filtered QuerySet.
        """
        return Account.objects.filter(**kwargs)

    def filter_with_select_related(
        self,
        *related_fields: str,
        **kwargs: object,
    ) -> QuerySet[Account]:
        """Filter accounts with select_related optimization.

        Args:
            *related_fields: Field names to optimize with select_related.
            **kwargs: Filter criteria (field=value pairs).

        Returns:
            QuerySet[Account]: Filtered QuerySet with select_related applied.
        """
        return Account.objects.filter(**kwargs).select_related(*related_fields)
