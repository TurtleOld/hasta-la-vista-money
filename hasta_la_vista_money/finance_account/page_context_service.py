"""Service for building page context for account views."""

from typing import Any

from django.db.models import QuerySet
from django.shortcuts import get_object_or_404

from hasta_la_vista_money.finance_account.forms import (
    AddAccountForm,
    TransferMoneyAccountForm,
)
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import User


class AccountPageContextService:
    """Service for building context data for account list page."""

    def __init__(
        self,
        account_repository: Any,
        transfer_money_log_repository: Any,
        account_service: Any,
        transfer_service: Any,
    ) -> None:
        """Initialize service with required repositories and services.

        Args:
            account_repository: Repository for account operations.
            transfer_money_log_repository: Repository for transfer log
                operations.
            account_service: Service for account business logic.
            transfer_service: Service for transfer operations.
        """
        self.account_repository = account_repository
        self.transfer_money_log_repository = transfer_money_log_repository
        self.account_service = account_service
        self.transfer_service = transfer_service

    def get_user_with_groups(self, user_pk: int) -> User:
        """Get user with prefetched groups to avoid repeated queries.

        Args:
            user_pk: Primary key of the user.

        Returns:
            User instance with prefetched groups.
        """
        return get_object_or_404(
            User.objects.prefetch_related('groups'),
            pk=user_pk,
        )

    def get_accounts_for_user_or_group(
        self,
        user: User,
        group_id: str | None,
    ) -> QuerySet[Account]:
        """Get accounts filtered by user or group.

        Args:
            user: User instance.
            group_id: Optional group ID for filtering.

        Returns:
            QuerySet of accounts.
        """
        return self.account_service.get_accounts_for_user_or_group(
            user,
            group_id,
        )

    def build_account_list_context(
        self,
        user: User,
        accounts: QuerySet[Account],
        group_id: str | None = None,
    ) -> dict[str, Any]:
        """Build complete context for account list page.

        Args:
            user: User instance with prefetched groups.
            accounts: QuerySet of accounts to display.
            group_id: Optional group ID for filtering.

        Returns:
            Dictionary with all context data for the page.
        """
        context: dict[str, Any] = {
            'accounts': accounts,
            'user_groups': user.groups.all(),
        }

        context.update(self._build_forms_context(user))
        context.update(self._build_transfer_log_context(user))
        context.update(self._build_sums_context(user))

        return context

    def _build_forms_context(self, user: User) -> dict[str, Any]:
        """Build context with forms for adding and transferring accounts.

        Args:
            user: User instance.

        Returns:
            Dictionary with forms.
        """
        account_transfer_money = (
            self.account_repository.get_by_user_with_related(user)
        )
        initial_form_data = {
            'from_account': account_transfer_money.first(),
            'to_account': account_transfer_money.first(),
        }
        return {
            'add_account_form': AddAccountForm(),
            'transfer_money_form': TransferMoneyAccountForm(
                user=user,
                transfer_service=self.transfer_service,
                account_repository=self.account_repository,
                initial=initial_form_data,
            ),
        }

    def _build_transfer_log_context(self, user: User) -> dict[str, Any]:
        """Build context with recent transfer logs.

        Args:
            user: User instance.

        Returns:
            Dictionary with transfer logs.
        """
        transfer_money_log = (
            self.transfer_money_log_repository.get_by_user_with_related(user)
        )
        return {
            'transfer_money_log': transfer_money_log,
        }

    def _build_sums_context(self, user: User) -> dict[str, Any]:
        """Build context with account balance statistics.

        Args:
            user: User instance.

        Returns:
            Dictionary with balance statistics.
        """
        accounts = self.account_repository.get_by_user_with_related(user)
        sum_all_accounts = self.account_service.get_sum_all_accounts(accounts)

        if user.groups.exists():
            accounts_in_group = self.account_repository.get_by_user_and_group(
                user,
                None,
            )
            sum_all_accounts_in_group = (
                self.account_service.get_sum_all_accounts(accounts_in_group)
            )
        else:
            accounts_user = self.account_repository.get_by_user_with_related(
                user
            )
            sum_all_accounts_in_group = (
                self.account_service.get_sum_all_accounts(accounts_user)
            )

        return {
            'sum_all_accounts': sum_all_accounts,
            'sum_all_accounts_in_group': sum_all_accounts_in_group,
        }
