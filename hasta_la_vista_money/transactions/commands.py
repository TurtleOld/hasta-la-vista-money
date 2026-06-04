"""Command objects for transaction operations."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import Category, Transaction
from hasta_la_vista_money.users.models import User


@dataclass(frozen=True, kw_only=True)
class CreateTransactionCommand:
    """Input data required to create a transaction."""

    user: User
    account: Account
    category: Category
    amount: Decimal
    transaction_date: date
    type_value: str


@dataclass(frozen=True, kw_only=True)
class UpdateTransactionCommand:
    """Input data required to update a transaction."""

    user: User
    transaction_obj: Transaction
    account: Account
    category: Category
    amount: Decimal
    transaction_date: date
    type_value: str
