from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.protocols.services import AccountServiceProtocol
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.income.repositories.income_repository import (
        IncomeRepository,
    )


class IncomeService:
    """Service for income operations.

    Handles creation, updating, deletion, and copying of income transactions
    with automatic account balance management.
    """

    def __init__(
        self,
        account_service: AccountServiceProtocol,
        income_repository: 'IncomeRepository',
    ) -> None:
        """Initialize IncomeService.

        Args:
            account_service: Service for account balance operations.
            income_repository: Repository for income data access.
        """
        self.account_service = account_service
        self.income_repository = income_repository

    @staticmethod
    def _validate_account_owner(user: User, account: Account) -> None:
        """Validate that user owns the account.

        Args:
            user: User to validate ownership for.
            account: Account to check ownership of.

        Raises:
            PermissionDenied: If user does not own the account.
        """
        if account.user != user:
            raise PermissionDenied(
                _('You do not have permission to add income to this account.'),
            )

    @staticmethod
    def _validate_income_owner(user: User, income: Income) -> None:
        """Validate that user owns the income.

        Args:
            user: User to validate ownership for.
            income: Income to check ownership of.

        Raises:
            PermissionDenied: If user does not own the income.
        """
        if income.user != user:
            raise PermissionDenied(
                _('You do not have permission to modify this income.'),
            )

    def add_income(
        self,
        *,
        user: User,
        account: Account,
        category: IncomeCategory,
        amount: Decimal,
        income_date: date,
    ) -> Income:
        """Add a new income transaction.

        Args:
            user: User creating the income.
            account: Account to add income to.
            category: Income category.
            amount: Income amount.
            income_date: Date of income.

        Returns:
            Created Income instance.

        Raises:
            PermissionDenied: If user does not own the account.
        """
        self._validate_account_owner(user, account)
        with transaction.atomic():
            income = self.income_repository.create_income(
                user=user,
                account=account,
                category=category,
                amount=amount,
                date=income_date,
            )
            self.account_service.refund_to_account(account, amount)
        return income

    def update_income(
        self,
        *,
        user: User,
        income: Income,
        account: Account,
        category: IncomeCategory,
        amount: Decimal,
        income_date: date,
    ) -> Income:
        """Update an existing income transaction.

        Automatically reconciles account balances if account or amount changes.

        Args:
            user: User updating the income.
            income: Income instance to update.
            account: New account for the income.
            category: New category for the income.
            amount: New amount for the income.
            income_date: New date for the income.

        Returns:
            Updated Income instance.

        Raises:
            PermissionDenied: If user does not own the income or account.
        """
        self._validate_income_owner(user, income)
        self._validate_account_owner(user, account)

        with transaction.atomic():
            old_account = income.account
            old_amount = income.amount

            if old_account.pk == account.pk:
                difference = amount - old_amount
                if difference > 0:
                    self.account_service.refund_to_account(account, difference)
                elif difference < 0:
                    self.account_service.apply_receipt_spend(
                        account,
                        abs(difference),
                    )
            else:
                self.account_service.apply_receipt_spend(
                    old_account, old_amount
                )
                self.account_service.refund_to_account(account, amount)

            income.account = account
            income.category = category
            income.amount = amount
            date_value = income_date
            if isinstance(date_value, date) and not isinstance(
                date_value, datetime
            ):
                date_value = timezone.make_aware(
                    datetime.combine(date_value, time.min),
                )
            elif isinstance(date_value, datetime) and timezone.is_naive(
                date_value
            ):
                date_value = timezone.make_aware(date_value)
            income.date = date_value
            income.save()
        return income

    def delete_income(self, *, user: User, income: Income) -> None:
        """Delete an income transaction.

        Automatically restores account balance by subtracting the income amount.

        Args:
            user: User deleting the income.
            income: Income instance to delete.

        Raises:
            PermissionDenied: If user does not own the income.
        """
        self._validate_income_owner(user, income)
        with transaction.atomic():
            self.account_service.apply_receipt_spend(
                income.account,
                income.amount,
            )
            income.delete()

    def copy_income(self, *, user: User, income_id: int) -> Income:
        """Copy an existing income transaction.

        Args:
            user: User copying the income.
            income_id: ID of income to copy.

        Returns:
            Newly created Income copy.

        Raises:
            PermissionDenied: If user does not own the income.
        """
        income = self.income_repository.get_by_id(income_id)
        if income.user != user:
            raise PermissionDenied(
                _('You do not have permission to copy this income.'),
            )
        with transaction.atomic():
            new_income = self.income_repository.create_income(
                user=income.user,
                account=income.account,
                category=income.category,
                amount=income.amount,
                date=income.date,
            )
            self.account_service.refund_to_account(
                new_income.account,
                new_income.amount,
            )
        return new_income
