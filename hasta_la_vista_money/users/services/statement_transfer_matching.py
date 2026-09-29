"""Shared matching of statement rows against recorded transfers.

A statement row mirrors a transfer when the movement sits on the same side
of the row's account, matches the amount exactly, and falls within one
calendar day. A transfer already bound to another row on the same account
is that end's mirror, so it is not offered again.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from django.utils import timezone

from hasta_la_vista_money.finance_account.models import TransferMoneyLog
from hasta_la_vista_money.transactions.models import TransactionType
from hasta_la_vista_money.users.models import BankStatementRow

if TYPE_CHECKING:
    from decimal import Decimal

    from django.db.models import QuerySet

    from hasta_la_vista_money.finance_account.models import Account
    from hasta_la_vista_money.users.models import User

TRANSFER_DATE_WINDOW = timedelta(days=1)


def find_mirroring_transfers(
    *,
    account: Account,
    user: User,
    transaction_type: str,
    amount: Decimal,
    row_date: date,
    exclude_row_id: int | None = None,
) -> QuerySet[TransferMoneyLog]:
    """Return transfers on the row's side, within one day, free on this end."""
    transfers = TransferMoneyLog.objects.filter(user=user, amount=amount)
    if transaction_type == TransactionType.EXPENSE:
        transfers = transfers.filter(from_account=account)
    else:
        transfers = transfers.filter(to_account=account)
    occupied = BankStatementRow.objects.filter(
        transfer__isnull=False,
        upload__account=account,
    )
    if exclude_row_id is not None:
        occupied = occupied.exclude(pk=exclude_row_id)
    return (
        transfers.filter(
            exchange_date__date__gte=row_date - TRANSFER_DATE_WINDOW,
            exchange_date__date__lte=row_date + TRANSFER_DATE_WINDOW,
        )
        .exclude(pk__in=occupied.values_list('transfer_id', flat=True))
        .order_by('exchange_date', 'pk')
    )


def local_row_date(transaction_date: datetime) -> date:
    """Return the local calendar date of a statement row timestamp."""
    return timezone.localtime(transaction_date).date()
