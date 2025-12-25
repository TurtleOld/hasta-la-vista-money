from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from dependency_injector import providers
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from config.containers import ApplicationContainer
from core.protocols.services import AccountServiceProtocol
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.income.services.income_ops import IncomeService


class IncomeOpsTest(TestCase):
    fixtures = [
        'users.yaml',
        'finance_account.yaml',
        'income.yaml',
        'income_cat.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)
        self.alt_account = Account.objects.get(pk=2)
        self.income = Income.objects.get(pk=1)
        self.category = IncomeCategory.objects.get(pk=1)

        self.other_user = User.objects.get(pk=2)
        self.other_category = IncomeCategory.objects.create(
            user=self.other_user,
            name='Other category',
        )
        self.other_account = Account.objects.create(
            user=self.other_user,
            name_account='Other account',
            balance=Decimal('500.00'),
            currency='RUB',
        )
        self.foreign_income = Income.objects.create(
            user=self.other_user,
            account=self.other_account,
            category=self.other_category,
            amount=Decimal('10.00'),
            date=self.income.date,
        )

        self.container = ApplicationContainer()
        self.account_service = MagicMock(spec=AccountServiceProtocol)
        self.container.core.account_service.override(
            providers.Object(self.account_service),
        )
        self.income_ops: IncomeService = self.container.income.income_ops()

    def tearDown(self) -> None:
        self.container.core.account_service.reset_override()

    def test_add_income_uses_account_service(self) -> None:
        amount = Decimal('100.00')

        new_income = self.income_ops.add_income(
            user=self.user,
            account=self.account,
            category=self.category,
            amount=amount,
            income_date=self.income.date,
        )

        self.account_service.refund_to_account.assert_called_once_with(
            self.account,
            amount,
        )
        self.assertEqual(new_income.amount, amount)
        self.assertEqual(new_income.user, self.user)

    def test_update_income_same_account_adjusts_difference(self) -> None:
        new_amount = Decimal('200000.00')

        self.income_ops.update_income(
            user=self.user,
            income=self.income,
            account=self.account,
            category=self.category,
            amount=new_amount,
            income_date=self.income.date,
        )

        self.account_service.refund_to_account.assert_called_once_with(
            self.account,
            Decimal('50000.00'),
        )
        self.account_service.apply_receipt_spend.assert_not_called()

    def test_update_income_account_change_reconciles_balances(self) -> None:
        new_amount = Decimal('250000.00')

        self.income_ops.update_income(
            user=self.user,
            income=self.income,
            account=self.alt_account,
            category=self.category,
            amount=new_amount,
            income_date=self.income.date,
        )

        self.account_service.apply_receipt_spend.assert_called_once_with(
            self.account,
            Decimal('150000.00'),
        )
        self.account_service.refund_to_account.assert_called_once_with(
            self.alt_account,
            new_amount,
        )

    def test_add_income_rejects_foreign_account(self) -> None:
        with self.assertRaises(PermissionDenied):
            self.income_ops.add_income(
                user=self.user,
                account=self.other_account,
                category=self.other_category,
                amount=Decimal('10.00'),
                income_date=self.income.date,
            )

    def test_update_income_rejects_foreign_income(self) -> None:
        with self.assertRaises(PermissionDenied):
            self.income_ops.update_income(
                user=self.user,
                income=self.foreign_income,
                account=self.other_account,
                category=self.other_category,
                amount=Decimal('10.00'),
                income_date=self.income.date,
            )

    def test_delete_income_rejects_foreign_income(self) -> None:
        with self.assertRaises(PermissionDenied):
            self.income_ops.delete_income(
                user=self.user,
                income=self.foreign_income,
            )

    def test_delete_income_uses_account_service(self) -> None:
        self.income_ops.delete_income(user=self.user, income=self.income)

        self.account_service.apply_receipt_spend.assert_called_once_with(
            self.account,
            self.income.amount,
        )
        with self.assertRaises(Income.DoesNotExist):
            Income.objects.get(pk=self.income.pk)

    def test_copy_income_adjusts_account_balance(self) -> None:
        copied_income = self.income_ops.copy_income(
            user=self.user,
            income_id=self.income.pk,
        )

        self.account_service.refund_to_account.assert_called_once_with(
            copied_income.account,
            copied_income.amount,
        )
        self.assertNotEqual(copied_income.pk, self.income.pk)
        self.assertEqual(copied_income.user, self.user)
