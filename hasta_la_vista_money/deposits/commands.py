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
