from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.users.models import User


@runtime_checkable
class IncomeServiceProtocol(Protocol):
    def add_income(
        self,
        *,
        user: User,
        account: Account,
        category: IncomeCategory,
        amount: Decimal,
        income_date: date,
    ) -> Income: ...

    def update_income(
        self,
        *,
        user: User,
        income: Income,
        account: Account,
        category: IncomeCategory,
        amount: Decimal,
        income_date: date,
    ) -> Income: ...

    def delete_income(
        self,
        *,
        user: User,
        income: Income,
    ) -> None: ...

    def copy_income(
        self,
        *,
        user: User,
        income_id: int,
    ) -> Income: ...
