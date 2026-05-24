"""Protocol interfaces for transaction services."""

from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import Category, Transaction
from hasta_la_vista_money.users.models import User


@runtime_checkable
class TransactionServiceProtocol(Protocol):
    """Protocol for the unified Transaction service."""

    def add_transaction(
        self,
        *,
        user: User,
        account: Account,
        category: Category,
        amount: Decimal,
        transaction_date: date,
        type_value: str,
    ) -> Transaction: ...

    def update_transaction(
        self,
        *,
        user: User,
        transaction_obj: Transaction,
        account: Account,
        category: Category,
        amount: Decimal,
        transaction_date: date,
        type_value: str,
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
