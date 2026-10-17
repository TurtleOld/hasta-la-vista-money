"""Rules for movements that a bank statement row points to."""

from django.db.models import QuerySet

from hasta_la_vista_money.finance_account.models import TransferMoneyLog
from hasta_la_vista_money.transactions.models import Transaction
from hasta_la_vista_money.users.models import BankStatementRow


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
    """Return rows closed by the movement to the pending state."""
    _linked_rows(movement).update(
        transaction=None,
        transfer=None,
        decision=BankStatementRow.Decision.PENDING,
        decided_at=None,
    )
