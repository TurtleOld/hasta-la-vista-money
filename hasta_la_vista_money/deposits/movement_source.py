"""Publishes deposit balance-affecting events to finance_account.

`finance_account.BalanceHistoryService` needs to know about deposit body
movements and interest payouts to reconstruct an account's balance at a
past moment, but must not import `deposits` models directly (see
ADR-0010 and `config/containers.py` for how the two containers are wired
together without a circular dependency).
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Final

from django.db.models import Q

from hasta_la_vista_money.deposits.models import (
    DepositCapitalizationEvent,
    DepositPrincipalEvent,
)
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.services import FinancialMovement

_TRANSFER_LOGGED_REVERSAL_TYPES: Final = (
    DepositPrincipalEvent.Type.FUNDING,
    DepositPrincipalEvent.Type.TOP_UP,
    DepositPrincipalEvent.Type.WITHDRAWAL,
)
_DEPOSIT_ACCOUNT_INFLOW_TYPES: Final = (
    DepositPrincipalEvent.Type.FUNDING,
    DepositPrincipalEvent.Type.TOP_UP,
)
_DEPOSIT_ACCOUNT_OUTFLOW_TYPES: Final = (
    DepositPrincipalEvent.Type.PLANNED_CLOSURE,
    DepositPrincipalEvent.Type.EARLY_CLOSURE,
)


def _deposit_account_delta(event: DepositPrincipalEvent) -> Decimal:
    """Return the original event's effect on the deposit's own account."""
    if event.type in _DEPOSIT_ACCOUNT_INFLOW_TYPES:
        return event.amount
    if event.type in _DEPOSIT_ACCOUNT_OUTFLOW_TYPES:
        return -event.amount
    return Decimal('0.00')


class DepositMovementSource:
    """Implements `FinancialMovementSourceProtocol` for deposit events."""

    def list_financial_movements(
        self,
        accounts: Sequence[Account],
        since: date,
    ) -> list[FinancialMovement]:
        account_ids = {account.pk for account in accounts}
        return [
            *self._principal_movements(account_ids, since),
            *self._capitalization_movements(account_ids, since),
        ]

    def _principal_movements(
        self,
        account_ids: set[int],
        since: date,
    ) -> list[FinancialMovement]:
        """Publish principal events not already recorded as transfers.

        Withdrawals and reversals of funding, top-ups and withdrawals are
        accompanied by a `TransferMoneyLog` row, which `BalanceHistoryService`
        already undoes; publishing them here would count them twice. A
        reversal event carries the original's type and accounts, so its
        movement is the original's with the opposite sign.
        """
        events = (
            DepositPrincipalEvent.objects.select_related(
                'deposit',
            )
            .filter(
                Q(source_account_id__in=account_ids)
                | Q(destination_account_id__in=account_ids)
                | Q(deposit__account_id__in=account_ids),
                effective_on__gte=since,
            )
            .exclude(
                Q(type=DepositPrincipalEvent.Type.WITHDRAWAL)
                | Q(
                    reversal_of__isnull=False,
                    type__in=_TRANSFER_LOGGED_REVERSAL_TYPES,
                ),
            )
        )
        movements: list[FinancialMovement] = []
        for event in events:
            sign = -1 if event.reversal_of_id else 1
            delta = Decimal('0.00')
            if event.source_account_id in account_ids:
                delta -= event.amount
            if event.destination_account_id in account_ids:
                delta += event.amount
            if event.deposit.account_id in account_ids:
                delta += _deposit_account_delta(event)
            if delta:
                movements.append(
                    FinancialMovement(
                        effective_on=event.effective_on,
                        delta=delta * sign,
                        description=event.get_type_display(),
                    ),
                )
        return movements

    def _capitalization_movements(
        self,
        account_ids: set[int],
        since: date,
    ) -> list[FinancialMovement]:
        capitalized_on_own_account = DepositCapitalizationEvent.objects.filter(
            deposit__account_id__in=account_ids,
            destination=DepositCapitalizationEvent.Destination.CAPITALIZATION,
            posting_on__gte=since,
        )
        paid_to_own_account = DepositCapitalizationEvent.objects.filter(
            destination_account_id__in=account_ids,
            posting_on__gte=since,
        )
        return [
            FinancialMovement(
                effective_on=event.posting_on,
                delta=-event.net if event.reversal_of_id else event.net,
                description='Капитализация процентов',
            )
            for event in (*capitalized_on_own_account, *paid_to_own_account)
        ]
