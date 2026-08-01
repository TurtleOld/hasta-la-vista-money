from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from hasta_la_vista_money.users.models import User


@dataclass(frozen=True)
class CreateDepositCommand:
    user: User
    name: str
    bank: str
    currency: str
    balance: Decimal
    opened_on: date
    matures_on: date
    annual_rate: Decimal


@dataclass(frozen=True)
class FundDepositCommand:
    """Command to fund a new term deposit from an owned source account.

    The source account must belong to the user and be in the same currency.
    The funding is executed as a financially neutral internal transfer.
    """

    user: User
    name: str
    bank: str
    currency: str
    amount: Decimal
    source_account_id: int
    opened_on: date
    matures_on: date
    annual_rate: Decimal


@dataclass(frozen=True)
class OpenExistingDepositCommand:
    """Command to record an already-active term deposit.

    Registers the deposit with its current balance and tracking start date
    through a neutral opening position — no monetary delta is applied,
    and no income or expense is created.
    """

    user: User
    name: str
    bank: str
    currency: str
    current_balance: Decimal
    tracking_started_on: date
    opened_on: date
    matures_on: date
    annual_rate: Decimal
