"""Reconstruct an account's balance at a past moment.

Replaces two independent, diverging reconstructions
(`ReceiptProcessingLogRepository.balance_after_receipt` and
`BalanceTrendService._get_balance_at_date`) with a single implementation
that also accounts for domains `finance_account` does not own (currently
just deposits, via `movement_sources`; see ADR-0010).
"""

from collections import defaultdict
from collections.abc import Iterator, Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

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
        later = sum(
            (delta for _, delta in self._events_after([account], moment)),
            Decimal('0.00'),
        )
        return account.balance - later

    def daily_balances(
        self,
        accounts: Sequence[Account],
        start: date,
        end: date,
    ) -> dict[date, Decimal]:
        """Return the summed balance of `accounts` at the end of each day.

        Same events as `balance_at`, read once for the whole period and
        undone day by day from the current balances.

        Args:
            accounts: Accounts whose balances are summed.
            start: First day of the series.
            end: Last day of the series.

        Returns:
            Day -> summed end-of-day balance, from `start` to `end`.
        """
        start_moment = timezone.make_aware(datetime.combine(start, time.max))
        by_day: defaultdict[date, Decimal] = defaultdict(Decimal)
        for day, delta in self._events_after(accounts, start_moment):
            by_day[day] += delta
        balance = sum((account.balance for account in accounts), Decimal(0))
        balance -= sum(
            (delta for day, delta in by_day.items() if day > end),
            Decimal(0),
        )
        balances: dict[date, Decimal] = {}
        day = end
        while day >= start:
            balances[day] = balance
            balance -= by_day[day]
            day -= timedelta(days=1)
        return dict(reversed(balances.items()))

    def _events_after(
        self,
        accounts: Sequence[Account],
        moment: datetime,
    ) -> Iterator[tuple[date, Decimal]]:
        """Yield `(day, balance delta)` of every event later than `moment`.

        Timestamped events are compared with `moment` exactly; movement
        source events from the day after `moment`'s calendar day.
        """
        account_ids = {account.pk for account in accounts}
        receipts = Receipt.objects.filter(
            account_id__in=account_ids,
            receipt_date__gt=moment,
        ).values_list('receipt_date', 'operation_type', 'total_sum')
        for at, operation_type, total_sum in receipts:
            yield (
                timezone.localdate(at),
                receipt_balance_delta(operation_type, total_sum),
            )

        transactions = Transaction.objects.filter(
            account_id__in=account_ids,
            date__gt=moment,
        ).values_list('date', 'type', 'amount')
        for at, transaction_type, amount in transactions:
            yield (
                timezone.localdate(at),
                amount
                if transaction_type == TransactionType.INCOME
                else -amount,
            )

        transfers = TransferMoneyLog.objects.filter(
            Q(from_account_id__in=account_ids)
            | Q(to_account_id__in=account_ids),
            exchange_date__gt=moment,
        ).values_list(
            'exchange_date',
            'from_account_id',
            'to_account_id',
            'amount',
        )
        for at, from_id, to_id, amount in transfers:
            delta = Decimal('0.00')
            if from_id in account_ids:
                delta -= amount
            if to_id in account_ids:
                delta += amount
            yield timezone.localdate(at), delta

        since = moment.date() + timedelta(days=1)
        for account in accounts:
            for source in self.movement_sources:
                for movement in source.list_financial_movements(
                    account,
                    since=since,
                ):
                    yield movement.effective_on, movement.delta
