"""Reconstruct an account's balance at a past moment.

Replaces two independent, diverging reconstructions
(`ReceiptProcessingLogRepository.balance_after_receipt` and
`BalanceTrendService._get_balance_at_date`) with a single implementation
that also accounts for domains `finance_account` does not own (currently
just deposits, via `movement_sources`; see ADR-0010).
"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Q

from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.finance_account.services.protocols import (
    FinancialMovementSourceProtocol,
)
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.receipts.services.receipt_creator import (
    receipt_balance_delta,
)
from hasta_la_vista_money.transactions.models import (
    Transaction,
    TransactionType,
)


class BalanceHistoryService:
    """Reconstructs an account's balance as of a past moment."""

    def __init__(
        self,
        movement_sources: list[FinancialMovementSourceProtocol],
    ) -> None:
        self.movement_sources = movement_sources

    def balance_at(self, account: Account, moment: datetime) -> Decimal:
        """Return the account's balance immediately after `moment`.

        Starts from the current balance and undoes every later event this
        service knows about: receipts, transactions, transfers (all
        compared with `moment`'s exact timestamp), and each registered
        movement source's events (compared at day granularity, since those
        events only carry a date — an event on `moment`'s own calendar day
        is treated as already reflected in the balance at `moment` and is
        not undone; only events on later days are).

        Args:
            account: Account to reconstruct the balance for.
            moment: Point in time to reconstruct the balance at.

        Returns:
            The account's balance immediately after `moment`.
        """
        balance = account.balance

        later_receipts = Receipt.objects.filter(
            account_id=account.pk,
            receipt_date__gt=moment,
        )
        for later_receipt in later_receipts:
            balance -= receipt_balance_delta(
                later_receipt.operation_type,
                later_receipt.total_sum,
            )

        later_transactions = Transaction.objects.filter(
            account_id=account.pk,
            date__gt=moment,
        )
        for later_transaction in later_transactions:
            delta = (
                later_transaction.amount
                if later_transaction.type == TransactionType.INCOME
                else -later_transaction.amount
            )
            balance -= delta

        later_transfers = TransferMoneyLog.objects.filter(
            Q(from_account_id=account.pk) | Q(to_account_id=account.pk),
            exchange_date__gt=moment,
        )
        for transfer in later_transfers:
            delta = Decimal('0.00')
            if transfer.from_account_id == account.pk:
                delta -= transfer.amount
            if transfer.to_account_id == account.pk:
                delta += transfer.amount
            balance -= delta

        since = moment.date() + timedelta(days=1)
        for source in self.movement_sources:
            for movement in source.list_financial_movements(
                account,
                since=since,
            ):
                balance -= movement.delta

        return balance
