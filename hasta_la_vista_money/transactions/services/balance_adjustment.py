"""Aligns an account balance with the actual one via a system movement."""

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction as db_transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.protocols.services import AccountServiceProtocol
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.repositories.account_repository import (  # noqa: E501
    AccountRepository,
)
from hasta_la_vista_money.system.models import AuditOperationKind
from hasta_la_vista_money.system.services.audit_context import audit_operation
from hasta_la_vista_money.transactions.models import (
    SystemCategoryKind,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.transactions.repositories import (
    CategoryRepository,
    TransactionRepository,
)
from hasta_la_vista_money.users.models import User


class BalanceAdjustmentService:
    """Posts the difference to the actual balance as a system movement."""

    def __init__(
        self,
        account_service: AccountServiceProtocol,
        account_repository: AccountRepository,
        transaction_repository: TransactionRepository,
        category_repository: CategoryRepository,
    ) -> None:
        self.account_service = account_service
        self.account_repository = account_repository
        self.transaction_repository = transaction_repository
        self.category_repository = category_repository

    def adjust_balance(
        self,
        *,
        user: User,
        account_id: int,
        actual_balance: Decimal,
    ) -> Transaction | None:
        """Return the posted movement, or None when nothing to adjust.

        The credit card income ban does not apply: the movement is not a
        real income.
        """
        with db_transaction.atomic():
            account = self.account_repository.get_by_ids_for_update(
                {account_id},
            ).get(account_id)
            if account is None or account.user_id != user.pk:
                raise PermissionDenied(
                    _('У вас нет прав на операции с этим счётом.'),
                )
            if account.is_deposit:
                raise ValidationError(
                    _('Корректировка остатка вклада недоступна.'),
                )
            if account.is_archived:
                raise ValidationError(
                    _('Архивный счёт недоступен для новых операций.'),
                )

            difference = actual_balance - account.balance
            if not difference:
                return None

            type_value = (
                TransactionType.INCOME
                if difference > 0
                else TransactionType.EXPENSE
            )
            category = self.category_repository.ensure_system_category(
                user=user,
                kind=SystemCategoryKind.BALANCE_ADJUSTMENT,
                type_value=type_value,
                name=constants.BALANCE_ADJUSTMENT_CATEGORY_NAME,
            )
            with audit_operation(kind=AuditOperationKind.BALANCE_ADJUSTMENT):
                movement = self.transaction_repository.create_transaction(
                    user=user,
                    account=account,
                    category=category,
                    amount=abs(difference),
                    date=timezone.now(),
                    type=type_value,
                )
                self.account_service.apply_account_deltas(
                    {account.pk: difference},
                )
            return movement
