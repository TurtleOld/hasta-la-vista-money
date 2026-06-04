"""Business logic for unified Transaction operations.

Provides create / update / delete / copy semantics with automatic account
balance reconciliation. Income transactions credit the account; expense
transactions debit it.
"""

from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied
from django.db import transaction as db_transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.protocols.services import AccountServiceProtocol
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.commands import (
    CreateTransactionCommand,
    UpdateTransactionCommand,
)
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.transactions.repositories.transaction_repository import (  # noqa: E501
        TransactionRepository,
    )


class TransactionService:
    """Service orchestrating Transaction CRUD with balance reconciliation."""

    def __init__(
        self,
        account_service: AccountServiceProtocol,
        transaction_repository: 'TransactionRepository',
    ) -> None:
        self.account_service = account_service
        self.transaction_repository = transaction_repository

    @staticmethod
    def _validate_account_owner(user: User, account: Account) -> None:
        if account.user != user:
            raise PermissionDenied(
                _('У вас нет прав на операции с этим счётом.'),
            )

    @staticmethod
    def _validate_transaction_owner(
        user: User,
        transaction_obj: Transaction,
    ) -> None:
        if transaction_obj.user != user:
            raise PermissionDenied(
                _('У вас нет прав на изменение этой операции.'),
            )

    @staticmethod
    def _validate_type_matches_category(
        type_value: str,
        category: Category,
    ) -> None:
        if category.type != type_value:
            raise ValueError(
                _(
                    'Тип категории не совпадает с типом операции.',
                ),
            )

    def _apply_balance_for_create(
        self,
        account: Account,
        amount: Decimal,
        type_value: str,
    ) -> None:
        if type_value == TransactionType.INCOME:
            self.account_service.refund_to_account(account, amount)
        else:
            self.account_service.apply_receipt_spend(account, amount)

    def _apply_balance_for_delete(
        self,
        account: Account,
        amount: Decimal,
        type_value: str,
    ) -> None:
        if type_value == TransactionType.INCOME:
            self.account_service.apply_receipt_spend(account, amount)
        else:
            self.account_service.refund_to_account(account, amount)

    def add_transaction(
        self,
        command: CreateTransactionCommand,
    ) -> Transaction:
        """Create a new transaction and adjust the account balance."""
        self._validate_account_owner(command.user, command.account)
        self._validate_type_matches_category(
            command.type_value,
            command.category,
        )

        with db_transaction.atomic():
            new_transaction = self.transaction_repository.create_transaction(
                user=command.user,
                account=command.account,
                category=command.category,
                amount=command.amount,
                date=command.transaction_date,
                type=command.type_value,
            )
            self._apply_balance_for_create(
                command.account,
                command.amount,
                command.type_value,
            )
        return new_transaction

    def update_transaction(
        self,
        command: UpdateTransactionCommand,
    ) -> Transaction:
        """Update a transaction and reconcile balances on both accounts."""
        self._validate_transaction_owner(
            command.user,
            command.transaction_obj,
        )
        self._validate_account_owner(command.user, command.account)
        self._validate_type_matches_category(
            command.type_value,
            command.category,
        )

        with db_transaction.atomic():
            old_account = command.transaction_obj.account
            old_amount = command.transaction_obj.amount
            old_type = command.transaction_obj.type

            self._apply_balance_for_delete(old_account, old_amount, old_type)
            self._apply_balance_for_create(
                command.account,
                command.amount,
                command.type_value,
            )

            command.transaction_obj.account = command.account
            command.transaction_obj.category = command.category
            command.transaction_obj.amount = command.amount
            command.transaction_obj.type = command.type_value

            date_value = command.transaction_date
            if isinstance(date_value, date) and not isinstance(
                date_value,
                datetime,
            ):
                date_value = timezone.make_aware(
                    datetime.combine(date_value, time.min),
                )
            elif isinstance(date_value, datetime) and timezone.is_naive(
                date_value,
            ):
                date_value = timezone.make_aware(date_value)
            command.transaction_obj.date = date_value
            command.transaction_obj.save()
        return command.transaction_obj

    def delete_transaction(
        self,
        *,
        user: User,
        transaction_obj: Transaction,
    ) -> None:
        """Delete a transaction and reverse its effect on the account."""
        self._validate_transaction_owner(user, transaction_obj)
        with db_transaction.atomic():
            self._apply_balance_for_delete(
                transaction_obj.account,
                transaction_obj.amount,
                transaction_obj.type,
            )
            transaction_obj.delete()

    def copy_transaction(
        self,
        *,
        user: User,
        transaction_id: int,
    ) -> Transaction:
        """Duplicate an existing transaction and adjust the balance."""
        original = self.transaction_repository.get_by_id(transaction_id)
        if original.user != user:
            raise PermissionDenied(
                _('У вас нет прав на копирование этой операции.'),
            )
        with db_transaction.atomic():
            new_transaction = self.transaction_repository.create_transaction(
                user=original.user,
                account=original.account,
                category=original.category,
                amount=original.amount,
                date=original.date,
                type=original.type,
            )
            self._apply_balance_for_create(
                new_transaction.account,
                new_transaction.amount,
                new_transaction.type,
            )
        return new_transaction
