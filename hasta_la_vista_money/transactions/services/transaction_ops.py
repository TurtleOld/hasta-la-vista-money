"""Business logic for unified Transaction operations.

Provides create / update / delete / copy semantics with automatic account
balance reconciliation. Income transactions credit the account; expense
transactions debit it.
"""

from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction as db_transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.protocols.services import AccountServiceProtocol
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.services.financial_change_hooks import (  # noqa: E501
    note_financial_change,
)
from hasta_la_vista_money.system.models import AuditOperationKind
from hasta_la_vista_money.system.services.audit_context import audit_operation
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
    from hasta_la_vista_money.finance_account.services.protocols import (
        AccountCoverageServiceProtocol,
    )
    from hasta_la_vista_money.transactions.repositories.transaction_repository import (  # noqa: E501
        TransactionRepository,
    )
    from hasta_la_vista_money.users.protocols.services import (
        StatementRowLinkServiceProtocol,
    )


class TransactionService:
    """Service orchestrating Transaction CRUD with balance reconciliation."""

    def __init__(
        self,
        account_service: AccountServiceProtocol,
        transaction_repository: 'TransactionRepository',
        statement_row_links: 'StatementRowLinkServiceProtocol',
        coverage_service: 'AccountCoverageServiceProtocol',
    ) -> None:
        self.account_service = account_service
        self.transaction_repository = transaction_repository
        self.statement_row_links = statement_row_links
        self.coverage_service = coverage_service

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
    def _validate_account_not_deposit(account: Account) -> None:
        if account.is_deposit:
            raise ValidationError(
                _(
                    'Операции по вкладу доступны только через сервис вкладов.',
                ),
            )

    @staticmethod
    def _validate_income_not_credit(
        account: Account,
        type_value: str,
    ) -> None:
        if (
            type_value == TransactionType.INCOME
            and account.type_account in constants.CREDIT_ACCOUNT_TYPES
        ):
            raise ValidationError(constants.CREDIT_CARD_INCOME_BAN)

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

    @staticmethod
    def _validate_category_owner(user: User, category: Category) -> None:
        if category.user_id != user.pk:
            raise PermissionDenied(
                _('У вас нет прав на использование этой категории.'),
            )

    @staticmethod
    def _balance_delta(amount: Decimal, type_value: str) -> Decimal:
        if type_value == TransactionType.INCOME:
            return amount
        return -amount

    @staticmethod
    def _kind_for_type(type_value: str) -> AuditOperationKind:
        if type_value == TransactionType.INCOME:
            return AuditOperationKind.INCOME
        return AuditOperationKind.EXPENSE

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
        self._validate_account_not_deposit(command.account)
        self._validate_income_not_credit(command.account, command.type_value)
        self._validate_type_matches_category(
            command.type_value,
            command.category,
        )
        self._validate_category_owner(command.user, command.category)

        with (
            db_transaction.atomic(),
            audit_operation(kind=self._kind_for_type(command.type_value)),
        ):
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
            note_financial_change(
                coverage_service=self.coverage_service,
                changes=[(command.account, command.transaction_date)],
                moments=[command.transaction_date],
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
        self._validate_account_not_deposit(command.account)
        self._validate_income_not_credit(command.account, command.type_value)
        self._validate_type_matches_category(
            command.type_value,
            command.category,
        )
        self._validate_category_owner(command.user, command.category)

        with (
            db_transaction.atomic(),
            audit_operation(kind=AuditOperationKind.TRANSACTION_EDIT),
        ):
            transaction_obj = self.transaction_repository.get_by_id_for_update(
                command.transaction_obj.pk,
            )
            self._validate_transaction_owner(command.user, transaction_obj)
            old_account = transaction_obj.account
            old_amount = transaction_obj.amount
            old_type = transaction_obj.type
            old_date = transaction_obj.date
            old_bank_day = transaction_obj.bank_calendar_date

            if self.statement_row_links.has_linked_row(transaction_obj) and (
                command.account.pk != old_account.pk
                or command.amount != old_amount
                or command.type_value != old_type
            ):
                raise ValidationError(
                    _(
                        'Нельзя менять сумму, счёт и тип операции, '
                        'связанной со строкой банковской выписки.',
                    ),
                )

            date_value = command.transaction_date
            bank_day = transaction_obj.bank_calendar_date
            if bank_day is not None:
                day_value: date
                if isinstance(date_value, datetime):
                    day_value = date_value.date()
                    if date_value != datetime.combine(
                        day_value,
                        time.min,
                        tzinfo=UTC,
                    ):
                        raise ValidationError(
                            _(
                                'Для операции с банковским днём укажите '
                                'дату без времени.',
                            ),
                        )
                elif isinstance(date_value, date):
                    day_value = date_value
                else:
                    raise ValidationError(
                        _(
                            'Для операции с банковским днём укажите дату '
                            'без времени.',
                        ),
                    )
                bank_day = day_value
                date_value = datetime.combine(
                    bank_day,
                    time.min,
                    tzinfo=UTC,
                )
            elif not isinstance(date_value, datetime):
                date_value = timezone.make_aware(
                    datetime.combine(date_value, time.min),
                )
            elif timezone.is_naive(date_value):
                date_value = timezone.make_aware(date_value)

            deltas = {
                old_account.pk: -self._balance_delta(old_amount, old_type),
            }
            deltas[command.account.pk] = deltas.get(
                command.account.pk,
                0,
            ) + self._balance_delta(command.amount, command.type_value)
            self.account_service.apply_account_deltas(deltas)

            transaction_obj.account = command.account
            transaction_obj.category = command.category
            transaction_obj.amount = command.amount
            transaction_obj.type = command.type_value
            transaction_obj.bank_calendar_date = bank_day
            transaction_obj.date = date_value
            transaction_obj.save()
            if (
                command.account.pk != old_account.pk
                or command.amount != old_amount
                or command.type_value != old_type
                or date_value != old_date
            ):
                note_financial_change(
                    coverage_service=self.coverage_service,
                    changes=[
                        (old_account, old_bank_day or old_date),
                        (command.account, bank_day or date_value),
                    ],
                    moments=[
                        old_bank_day or old_date,
                        bank_day or date_value,
                    ],
                )
        return transaction_obj

    def delete_transaction(
        self,
        *,
        user: User,
        transaction_obj: Transaction,
    ) -> None:
        """Delete a transaction and reverse its effect on the account."""
        self._validate_transaction_owner(user, transaction_obj)
        with (
            db_transaction.atomic(),
            audit_operation(kind=AuditOperationKind.TRANSACTION_DELETE),
        ):
            transaction_obj = self.transaction_repository.get_by_id_for_update(
                transaction_obj.pk,
            )
            self._validate_transaction_owner(user, transaction_obj)
            self._apply_balance_for_delete(
                transaction_obj.account,
                transaction_obj.amount,
                transaction_obj.type,
            )
            self.statement_row_links.release_linked_rows(transaction_obj)
            account = transaction_obj.account
            transaction_date = (
                transaction_obj.bank_calendar_date or transaction_obj.date
            )
            transaction_obj.delete()
            note_financial_change(
                coverage_service=self.coverage_service,
                changes=[(account, transaction_date)],
                moments=[transaction_date],
            )

    def copy_transaction(
        self,
        *,
        user: User,
        transaction_id: int,
    ) -> Transaction:
        """Duplicate a transaction with the current time and adjust balance."""
        with db_transaction.atomic():
            original = self.transaction_repository.get_by_id_for_update(
                transaction_id,
            )
            if original.user != user:
                raise PermissionDenied(
                    _('У вас нет прав на копирование этой операции.'),
                )
            self._validate_income_not_credit(original.account, original.type)
            with audit_operation(kind=self._kind_for_type(original.type)):
                repository = self.transaction_repository
                new_transaction = repository.create_transaction(
                    user=original.user,
                    account=original.account,
                    category=original.category,
                    amount=original.amount,
                    date=timezone.now(),
                    type=original.type,
                )
                self._apply_balance_for_create(
                    new_transaction.account,
                    new_transaction.amount,
                    new_transaction.type,
                )
                note_financial_change(
                    coverage_service=self.coverage_service,
                    changes=[(new_transaction.account, new_transaction.date)],
                    moments=[new_transaction.date],
                )
        return new_transaction
