"""Publishes deposit balance-affecting events to finance_account.

`finance_account.BalanceHistoryService` needs to know about deposit body
movements and interest payouts to reconstruct an account's balance at a
past moment, but must not import `deposits` models directly (see
ADR-0010 and `config/containers.py` for how the two containers are wired
together without a circular dependency).
"""

from datetime import date

from hasta_la_vista_money.deposits.models import (
    DepositCapitalizationEvent,
    DepositPrincipalEvent,
)
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.services import FinancialMovement


class DepositMovementSource:
    """Implements `FinancialMovementSourceProtocol` for deposit events."""

    def list_financial_movements(
        self,
        account: Account,
        since: date,
    ) -> list[FinancialMovement]:
        return [
            *self._principal_movements(account, since),
            *self._capitalization_movements(account, since),
        ]

    def _principal_movements(
        self,
        account: Account,
        since: date,
    ) -> list[FinancialMovement]:
        outgoing = DepositPrincipalEvent.objects.filter(
            source_account=account,
            effective_on__gte=since,
        )
        incoming = DepositPrincipalEvent.objects.filter(
            destination_account=account,
            effective_on__gte=since,
        )
        return [
            FinancialMovement(
                effective_on=event.effective_on,
                delta=-event.amount,
                description=event.get_type_display(),
            )
            for event in outgoing
        ] + [
            FinancialMovement(
                effective_on=event.effective_on,
                delta=event.amount,
                description=event.get_type_display(),
            )
            for event in incoming
        ]

    def _capitalization_movements(
        self,
        account: Account,
        since: date,
    ) -> list[FinancialMovement]:
        capitalized_on_own_account = DepositCapitalizationEvent.objects.filter(
            deposit__account=account,
            destination=DepositCapitalizationEvent.Destination.CAPITALIZATION,
            posting_on__gte=since,
        )
        paid_to_own_account = DepositCapitalizationEvent.objects.filter(
            destination_account=account,
            posting_on__gte=since,
        )
        return [
            FinancialMovement(
                effective_on=event.posting_on,
                delta=event.net,
                description='Капитализация процентов',
            )
            for event in (*capitalized_on_own_account, *paid_to_own_account)
        ]
