"""Shared matching of statement rows against recorded transfers.

A statement row mirrors a transfer when the movement sits on the same side
of the row's account, matches the amount exactly, and falls within one
calendar day. A transfer already bound to another row on the same account
is that end's mirror, so it is not offered again.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from django.db.models import Q
from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import TransferMoneyLog
from hasta_la_vista_money.transactions.models import TransactionType
from hasta_la_vista_money.users.models import BankStatementRow

if TYPE_CHECKING:
    from decimal import Decimal

    from django.db.models import QuerySet

    from hasta_la_vista_money.finance_account.models import Account
    from hasta_la_vista_money.users.models import User

TRANSFER_DATE_WINDOW = timedelta(
    days=constants.STATEMENT_TRANSFER_DATE_WINDOW_DAYS,
)


def mirroring_transfer_q(
    *,
    account_id: int,
    user_id: int,
    transaction_type: str,
    amount: Decimal,
    row_date: date,
) -> Q:
    """The rule: the row's side of the account, same amount, within a day."""
    side = (
        Q(from_account_id=account_id)
        if transaction_type == TransactionType.EXPENSE
        else Q(to_account_id=account_id)
    )
    return side & Q(
        user_id=user_id,
        amount=amount,
        exchange_date__date__gte=row_date - TRANSFER_DATE_WINDOW,
        exchange_date__date__lte=row_date + TRANSFER_DATE_WINDOW,
    )


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
    occupied = BankStatementRow.objects.filter(
        transfer__isnull=False,
        upload__account=account,
    )
    if exclude_row_id is not None:
        occupied = occupied.exclude(pk=exclude_row_id)
    return (
        TransferMoneyLog.objects.filter(
            mirroring_transfer_q(
                account_id=account.pk,
                user_id=user.pk,
                transaction_type=transaction_type,
                amount=amount,
                row_date=row_date,
            ),
        )
        .exclude(pk__in=occupied.values_list('transfer_id', flat=True))
        .order_by('exchange_date', 'pk')
    )


def local_row_date(transaction_date: datetime) -> date:
    """Return the local calendar date of a statement row timestamp."""
    return timezone.localtime(transaction_date).date()
