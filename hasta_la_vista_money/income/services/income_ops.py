from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _

from core.protocols.services import AccountServiceProtocol
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.users.models import User


class IncomeOps:
    def __init__(
        self,
        account_service: AccountServiceProtocol,
    ) -> None:
        self.account_service = account_service

    @staticmethod
    def _validate_account_owner(user: User, account: Account) -> None:
        if account.user != user:
            raise PermissionDenied(
                _('You do not have permission to add income to this account.'),
            )

    @staticmethod
    def _validate_income_owner(user: User, income: Income) -> None:
        if income.user != user:
            raise PermissionDenied(
                _('You do not have permission to modify this income.'),
            )

    def add_income(
        self,
        *,
        user: User,
        account: Account,
        category: IncomeCategory,
        amount: Decimal,
        when: date,
    ) -> Income:
        self._validate_account_owner(user, account)
        with transaction.atomic():
            income = Income.objects.create(
                user=user,
                account=account,
                category=category,
                amount=amount,
                date=when,
            )
            self.account_service.refund_to_account(account, amount)
        return income

    def update_income(
        self,
        *,
        user: User,
        income: Income,
        account: Account,
        category: IncomeCategory,
        amount: Decimal,
        when: date,
    ) -> Income:
        self._validate_income_owner(user, income)
        self._validate_account_owner(user, account)

        with transaction.atomic():
            old_account = income.account
            old_amount = income.amount

            if old_account.pk == account.pk:
                difference = amount - old_amount
                if difference > 0:
                    self.account_service.refund_to_account(account, difference)
                elif difference < 0:
                    self.account_service.apply_receipt_spend(
                        account,
                        abs(difference),
                    )
            else:
                self.account_service.apply_receipt_spend(old_account, old_amount)
                self.account_service.refund_to_account(account, amount)

            income.account = account
            income.category = category
            income.amount = amount
            income.date = when
            income.save()
        return income

    def delete_income(self, *, user: User, income: Income) -> None:
        self._validate_income_owner(user, income)
        with transaction.atomic():
            self.account_service.apply_receipt_spend(
                income.account,
                income.amount,
            )
            income.delete()

    def copy_income(self, *, user: User, income_id: int) -> Income:
        income = get_object_or_404(Income, pk=income_id, user=user)
        with transaction.atomic():
            new_income = Income.objects.create(
                user=income.user,
                account=income.account,
                category=income.category,
                amount=income.amount,
                date=income.date,
            )
            self.account_service.refund_to_account(
                new_income.account,
                new_income.amount,
            )
        return new_income
