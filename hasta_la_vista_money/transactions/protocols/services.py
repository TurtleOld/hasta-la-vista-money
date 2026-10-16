"""Protocol interfaces for transaction services."""

from decimal import Decimal
from typing import Protocol, runtime_checkable

from hasta_la_vista_money.transactions.commands import (
    CreateTransactionCommand,
    UpdateTransactionCommand,
)
from hasta_la_vista_money.transactions.models import Transaction
from hasta_la_vista_money.users.models import User


@runtime_checkable
class TransactionServiceProtocol(Protocol):
    """Protocol for the unified Transaction service."""

    def add_transaction(
        self,
        command: CreateTransactionCommand,
    ) -> Transaction: ...

    def update_transaction(
        self,
        command: UpdateTransactionCommand,
    ) -> Transaction: ...

    def delete_transaction(
        self,
        *,
        user: User,
        transaction_obj: Transaction,
    ) -> None: ...

    def copy_transaction(
        self,
        *,
        user: User,
        transaction_id: int,
    ) -> Transaction: ...


@runtime_checkable
class BalanceAdjustmentServiceProtocol(Protocol):
    """Protocol for aligning an account balance with the actual one."""

    def adjust_balance(
        self,
        *,
        user: User,
        account_id: int,
        actual_balance: Decimal,
    ) -> Transaction | None: ...
