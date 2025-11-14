from datetime import date
from decimal import Decimal

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.services import income as income_services
from hasta_la_vista_money.users.models import User


class IncomeOps:
    @staticmethod
    def add_income(
        *,
        user: User,
        account: Account,
        category: IncomeCategory,
        amount: Decimal,
        when: date,
    ) -> Income:
        return income_services.add_income(user, account, category, amount, when)

    @staticmethod
    def update_income(
        *,
        user: User,
        income: Income,
        account: Account,
        category: IncomeCategory,
        amount: Decimal,
        when: date,
    ) -> Income:
        return income_services.update_income(
            user,
            income,
            account,
            category,
            amount,
            when,
        )

    @staticmethod
    def delete_income(*, user: User, income: Income) -> None:
        income_services.delete_income(user, income)

    @staticmethod
    def copy_income(*, user: User, income_id: int) -> Income:
        return income_services.copy_income(user, income_id)
