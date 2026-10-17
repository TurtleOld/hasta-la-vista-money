"""Rules for movements that a bank statement row points to."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Q, QuerySet
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.transactions.models import Transaction
from hasta_la_vista_money.users.models import BankStatementRow

_REPAYMENT_ROW = Q(
    upload__account__type_account__in=constants.CREDIT_ACCOUNT_TYPES,
    transaction_type=BankStatementRow.TransactionType.INCOME,
)


def _linked_rows(
    movement: Transaction | TransferMoneyLog,
) -> QuerySet[BankStatementRow]:
    if isinstance(movement, TransferMoneyLog):
        return BankStatementRow.objects.filter(transfer=movement)
    return BankStatementRow.objects.filter(transaction=movement)


def has_linked_row(movement: Transaction | TransferMoneyLog) -> bool:
    """Return whether a statement row is closed by this movement."""
    return _linked_rows(movement).exists()


def release_linked_rows(movement: Transaction | TransferMoneyLog) -> None:
    """Reopen rows closed by the movement.

    A credit-account repayment goes back to waiting for a transfer,
    every other row goes back to the pending decision.
    """
    rows = _linked_rows(movement)
    rows.filter(_REPAYMENT_ROW).update(
        transaction=None,
        transfer=None,
        decision=BankStatementRow.Decision.NEEDS_TRANSFER,
        decided_at=None,
    )
    rows.exclude(_REPAYMENT_ROW).update(
        transaction=None,
        transfer=None,
        decision=BankStatementRow.Decision.PENDING,
        decided_at=None,
    )


def lock_repayment_row(
    row_id: int,
    *,
    to_account: Account,
    amount: Decimal,
) -> BankStatementRow:
    """Lock the open repayment row that a transfer is about to close."""
    row = (
        BankStatementRow.objects.select_for_update()
        .select_related('upload')
        .filter(
            pk=row_id,
            upload__user_id=to_account.user_id,
            upload__account=to_account,
        )
        .first()
    )
    if row is None:
        raise ValidationError(
            _('Строка выписки не относится к счёту получателя.'),
        )
    if row.decision != BankStatementRow.Decision.NEEDS_TRANSFER:
        raise ValidationError(_('Строка выписки уже закрыта.'))
    if row.amount != amount:
        raise ValidationError(
            _('Сумма перевода должна совпадать с суммой строки выписки.'),
        )
    return row
