"""Protocol interfaces for transaction services."""

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
