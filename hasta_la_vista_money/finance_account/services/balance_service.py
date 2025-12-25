"""Service for account balance operations."""

from decimal import Decimal

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.validators import (
    validate_account_balance,
    validate_positive_amount,
)


class BalanceService:
    """Service for managing account balance operations.

    Handles balance adjustments, refunds, and reconciliation when
    transactions change accounts or amounts.
    """

    def apply_receipt_spend(self, account: Account, amount: Decimal) -> Account:
        """Apply spending by receipt to the account balance with validation.

        Args:
            account: Account to apply spending to.
            amount: Amount to subtract from balance. Must be positive.

        Returns:
            Updated Account instance.

        Raises:
            ValidationError: If amount is invalid or account has
                insufficient funds.
        """
        validate_positive_amount(amount)
        validate_account_balance(account, amount)
        account.balance -= amount
        account.save()
        return account

    def refund_to_account(self, account: Account, amount: Decimal) -> Account:
        """Return money to account balance with validation.

        Args:
            account: Account to refund to.
            amount: Amount to add to balance. Must be positive.

        Returns:
            Updated Account instance.

        Raises:
            ValidationError: If amount is invalid.
        """
        validate_positive_amount(amount)
        account.balance += amount
        account.save()
        return account

    def _adjust_balance_on_same_account(
        self,
        account: Account,
        old_total_sum: Decimal,
        new_total_sum: Decimal,
    ) -> None:
        """Adjust balance when transaction amount changes on same account.

        Args:
            account: Account to adjust balance for.
            old_total_sum: Previous transaction amount.
            new_total_sum: New transaction amount.
        """
        difference = new_total_sum - old_total_sum
        if difference == 0:
            return
        if difference > 0:
            self.apply_receipt_spend(account, difference)
        else:
            self.refund_to_account(account, abs(difference))

    def _adjust_balance_on_account_change(
        self,
        old_account: Account,
        new_account: Account,
        old_total_sum: Decimal,
        new_total_sum: Decimal,
    ) -> None:
        """Adjust balance when transaction account changes.

        Args:
            old_account: Previous account.
            new_account: New account.
            old_total_sum: Previous transaction amount.
            new_total_sum: New transaction amount.
        """
        self.refund_to_account(old_account, old_total_sum)
        self.apply_receipt_spend(new_account, new_total_sum)

    def _should_adjust_same_account(
        self,
        old_account: Account,
        new_account: Account,
    ) -> bool:
        """Check if both accounts are the same.

        Args:
            old_account: Previous account.
            new_account: New account.

        Returns:
            True if accounts are the same, False otherwise.
        """
        return old_account.pk == new_account.pk

    def reconcile_account_balances(
        self,
        old_account: Account,
        new_account: Account,
        old_total_sum: Decimal,
        new_total_sum: Decimal,
    ) -> None:
        """Reconcile account balances when amount or account changes.

        Handles two scenarios:
        1. Same account: adjusts balance by difference
        2. Different accounts: refunds old account, applies to new account

        Args:
            old_account: Account before change.
            new_account: Account after change.
            old_total_sum: Total amount before change.
            new_total_sum: Total amount after change.
        """
        if self._should_adjust_same_account(old_account, new_account):
            self._adjust_balance_on_same_account(
                old_account,
                old_total_sum,
                new_total_sum,
            )
        else:
            self._adjust_balance_on_account_change(
                old_account,
                new_account,
                old_total_sum,
                new_total_sum,
            )
