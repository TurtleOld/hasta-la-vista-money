from typing import Protocol

from django.db.models import QuerySet

from hasta_la_vista_money.deposits.commands import (
    CreateDepositCommand,
    FundDepositCommand,
    OpenExistingDepositCommand,
)
from hasta_la_vista_money.deposits.models import Deposit
from hasta_la_vista_money.users.models import User


class DepositServiceProtocol(Protocol):
    def open_existing_term_deposit(
        self,
        command: OpenExistingDepositCommand,
    ) -> Deposit:
        """Record an already-active term deposit via a neutral opening position.

        Args:
            command: Details of the existing deposit to record.

        Returns:
            The created Deposit with an immutable opening-position event.
        """

    def create_funded_term_deposit(
        self,
        command: FundDepositCommand,
    ) -> Deposit:
        """Fund a new term deposit by transferring from an owned source account.

        Args:
            command: Funding details including source account and amount.

        Returns:
            The created Deposit with an immutable funding event.

        Raises:
            ValidationError: If the source account is invalid or insufficient.
        """

    def create_term_deposit(
        self,
        command: CreateDepositCommand,
    ) -> Deposit:
        """Create a term deposit with its initial balance.

        Args:
            command: Deposit creation parameters.

        Returns:
            The created Deposit.
        """

    def get_user_deposits(self, user: User) -> QuerySet[Deposit]: ...

    def get_user_deposit(self, deposit_id: int, user: User) -> Deposit: ...
