from decimal import Decimal
from typing import ClassVar

from django.test import TestCase
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.users.models import User


class IncomeModelTest(TestCase):
    """
    Test cases for the Income model.
    """

    fixtures: ClassVar[list[str]] = [
        'users.yaml',
        'finance_account.yaml',
        'income.yaml',
        'income_cat.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)
        self.income_type = IncomeCategory.objects.get(pk=1)

    def test_income_model_str(self) -> None:
        income = Income.objects.get(pk=1)
        self.assertEqual(str(income), str(income.category))

    def test_income_model_meta(self) -> None:
        self.assertEqual(Income._meta.model_name, 'income')
        self.assertEqual(Income._meta.app_label, 'income')

    def test_income_model_created_at(self) -> None:
        income = Income.objects.create(
            user=self.user,
            account=self.account,
            category=self.income_type,
            date=timezone.now(),
            amount=Decimal('1000.00'),
        )
        self.assertIsNotNone(income.created_at)


class IncomeCategoryModelTest(TestCase):
    """
    Test cases for the IncomeCategory model.
    """

    fixtures: ClassVar[list[str]] = ['users.yaml', 'income_cat.yaml']

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.parent_category = IncomeCategory.objects.get(name='Зарплата')
        self.income_type = IncomeCategory.objects.get(pk=1)

    def test_income_category_model_str(self) -> None:
        self.assertEqual(str(self.income_type), self.income_type.name)

    def test_income_category_model_meta(self) -> None:
        self.assertEqual(IncomeCategory._meta.model_name, 'incomecategory')
        self.assertEqual(IncomeCategory._meta.app_label, 'income')
        self.assertEqual(IncomeCategory._meta.ordering, ['parent_category_id'])

    def test_income_category_without_parent(self) -> None:
        category = IncomeCategory.objects.create(
            user=self.user,
            name='Test Category Without Parent',
        )
        self.assertIsNone(category.parent_category)

    def test_income_category_with_parent(self) -> None:
        child_category = IncomeCategory.objects.create(
            user=self.user,
            name='Child Category',
            parent_category=self.parent_category,
        )
        self.assertEqual(child_category.parent_category, self.parent_category)
