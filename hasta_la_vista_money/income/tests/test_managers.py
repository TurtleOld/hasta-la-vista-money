from datetime import timedelta
from decimal import Decimal
from typing import ClassVar

from django.test import TestCase
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.users.models import User


class IncomeQuerySetTest(TestCase):
    """Тесты для IncomeQuerySet."""

    fixtures: ClassVar[list[str]] = [  # type: ignore[misc]
        'users.yaml',
        'finance_account.yaml',
        'income_cat.yaml',
    ]

    def setUp(self) -> None:
        self.user1 = User.objects.get(pk=1)
        self.user2 = User.objects.get(pk=2)
        self.account1 = Account.objects.get(pk=1)
        self.account2 = Account.objects.get(pk=2)

        self.category1 = IncomeCategory.objects.create(
            user=self.user1,
            name='Test Category',
        )
        self.category2 = IncomeCategory.objects.create(
            user=self.user1,
            name='Subcategory',
            parent_category=self.category1,
        )

        self.today = timezone.now()
        self.yesterday = self.today - timedelta(days=1)
        self.tomorrow = self.today + timedelta(days=1)
        self.week_ago = self.today - timedelta(days=7)

        Income.objects.create(
            user=self.user1,
            account=self.account1,
            category=self.category1,
            date=self.today,
            amount=Decimal('1000.00'),
        )
        Income.objects.create(
            user=self.user1,
            account=self.account1,
            category=self.category2,
            date=self.yesterday,
            amount=Decimal('500.00'),
        )
        category_user2 = IncomeCategory.objects.create(
            user=self.user2,
            name='User2 Category',
        )
        Income.objects.create(
            user=self.user2,
            account=self.account2,
            category=category_user2,
            date=self.today,
            amount=Decimal('2000.00'),
        )

    def test_for_user(self) -> None:
        """Тест фильтрации по пользователю."""
        incomes = Income.objects.for_user(self.user1)
        self.assertEqual(incomes.count(), 2)
        for income in incomes:
            self.assertEqual(income.user, self.user1)

    def test_for_period(self) -> None:
        """Тест фильтрации по периоду."""
        incomes = Income.objects.for_user(self.user1).for_period(
            self.yesterday.date(),
            self.today.date(),
        )
        self.assertEqual(incomes.count(), 2)
        for income in incomes:
            self.assertGreaterEqual(income.date.date(), self.yesterday.date())
            self.assertLessEqual(income.date.date(), self.today.date())

    def test_for_category(self) -> None:
        """Тест фильтрации по категории с подкатегориями."""
        incomes = Income.objects.for_category(self.category1)
        self.assertEqual(incomes.count(), 2)

    def test_total_amount(self) -> None:
        """Тест расчёта общей суммы."""
        total = Income.objects.for_user(self.user1).total_amount()
        self.assertEqual(total, Decimal('1500.00'))

    def test_total_amount_empty(self) -> None:
        """Тест расчёта общей суммы для пустого queryset."""
        total = Income.objects.filter(amount__lt=0).total_amount()
        self.assertEqual(total, 0)

    def test_by_month(self) -> None:
        """Тест группировки по месяцам."""
        by_month = Income.objects.for_user(self.user1).by_month()
        self.assertGreater(len(by_month), 0)
        for item in by_month:
            self.assertIn('month', item)
            self.assertIn('total', item)


class IncomeManagerTest(TestCase):
    """Тесты для IncomeManager."""

    fixtures: ClassVar[list[str]] = [  # type: ignore[misc]
        'users.yaml',
        'finance_account.yaml',
        'income_cat.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)
        self.category = IncomeCategory.objects.create(
            user=self.user,
            name='Test Manager Category',
        )

        self.today = timezone.now()
        self.yesterday = self.today - timedelta(days=1)

        Income.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            date=self.today,
            amount=Decimal('1000.00'),
        )
        Income.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            date=self.yesterday,
            amount=Decimal('500.00'),
        )

    def test_manager_for_user(self) -> None:
        """Тест метода for_user менеджера."""
        incomes = Income.objects.for_user(self.user)
        self.assertEqual(incomes.count(), 2)

    def test_manager_for_period(self) -> None:
        """Тест метода for_period менеджера."""
        incomes = Income.objects.for_period(
            self.yesterday.date(),
            self.today.date(),
        )
        self.assertEqual(incomes.count(), 2)

    def test_manager_for_category(self) -> None:
        """Тест метода for_category менеджера."""
        incomes = Income.objects.for_category(self.category)
        self.assertEqual(incomes.count(), 2)

    def test_manager_total_amount(self) -> None:
        """Тест метода total_amount менеджера."""
        total = Income.objects.filter(user=self.user).total_amount()
        self.assertEqual(total, Decimal('1500.00'))

    def test_manager_by_month(self) -> None:
        """Тест метода by_month менеджера."""
        by_month = Income.objects.filter(user=self.user).by_month()
        self.assertGreater(len(by_month), 0)
