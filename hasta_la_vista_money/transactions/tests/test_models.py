"""Tests for the unified Transaction model and its QuerySet manager."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import ClassVar

from django.db import IntegrityError, transaction
from django.test import TestCase

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User


class TransactionQuerySetTest(TestCase):
    """Cover TransactionQuerySet shortcuts and aggregates."""

    fixtures: ClassVar[list[str]] = [
        'users.yaml',
        'finance_account.yaml',
    ]

    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = User.objects.get(pk=1)
        cls.account = Account.objects.get(pk=1)
        cls.income_category = Category.objects.create(
            user=cls.user,
            name='Зарплата',
            type=TransactionType.INCOME,
        )
        cls.expense_root = Category.objects.create(
            user=cls.user,
            name='Дом',
            type=TransactionType.EXPENSE,
        )
        cls.expense_child = Category.objects.create(
            user=cls.user,
            name='ЖКХ',
            type=TransactionType.EXPENSE,
            parent_category=cls.expense_root,
        )

        cls.income = Transaction.objects.create(
            user=cls.user,
            account=cls.account,
            category=cls.income_category,
            amount=Decimal('1000.00'),
            date=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
            type=TransactionType.INCOME,
        )
        cls.expense_a = Transaction.objects.create(
            user=cls.user,
            account=cls.account,
            category=cls.expense_root,
            amount=Decimal('200.00'),
            date=datetime(2026, 2, 5, 10, 0, tzinfo=UTC),
            type=TransactionType.EXPENSE,
        )
        cls.expense_b = Transaction.objects.create(
            user=cls.user,
            account=cls.account,
            category=cls.expense_child,
            amount=Decimal('300.00'),
            date=datetime(2026, 2, 20, 10, 0, tzinfo=UTC),
            type=TransactionType.EXPENSE,
        )

    def test_incomes_filters_only_income(self) -> None:
        self.assertEqual(
            list(Transaction.objects.incomes()),
            [self.income],
        )

    def test_expenses_filters_only_expense(self) -> None:
        self.assertEqual(
            set(Transaction.objects.expenses()),
            {self.expense_a, self.expense_b},
        )

    def test_for_user_filters_by_user(self) -> None:
        self.assertEqual(Transaction.objects.for_user(self.user).count(), 3)

    def test_for_period_includes_only_matching_dates(self) -> None:
        result = Transaction.objects.for_period(
            date(2026, 2, 1),
            date(2026, 2, 28),
        )
        self.assertEqual(set(result), {self.expense_a, self.expense_b})

    def test_for_category_includes_direct_children(self) -> None:
        result = Transaction.objects.for_category(self.expense_root)
        self.assertEqual(set(result), {self.expense_a, self.expense_b})

    def test_total_amount_returns_sum(self) -> None:
        self.assertEqual(
            Transaction.objects.for_user(self.user).total_amount(),
            Decimal('1500.00'),
        )

    def test_total_amount_returns_zero_for_empty_queryset(self) -> None:
        Transaction.objects.all().delete()
        self.assertEqual(Transaction.objects.total_amount(), 0)

    def test_by_month_groups_aggregated_totals(self) -> None:
        grouped = {
            row['month'].date(): row['total']
            for row in Transaction.objects.for_user(self.user).by_month()
        }
        self.assertEqual(grouped[date(2026, 1, 1)], Decimal('1000.00'))
        self.assertEqual(grouped[date(2026, 2, 1)], Decimal('500.00'))


class CategoryUniqueConstraintTest(TestCase):
    """Verify the per-user/per-type uniqueness on Category."""

    fixtures: ClassVar[list[str]] = ['users.yaml']

    def test_same_name_allowed_across_types(self) -> None:
        user = User.objects.get(pk=1)
        Category.objects.create(
            user=user,
            name='Подарки',
            type=TransactionType.INCOME,
        )
        Category.objects.create(
            user=user,
            name='Подарки',
            type=TransactionType.EXPENSE,
        )
        self.assertEqual(
            Category.objects.filter(user=user, name='Подарки').count(),
            2,
        )

    def test_duplicate_same_type_rejected(self) -> None:
        user = User.objects.get(pk=1)
        Category.objects.create(
            user=user,
            name='Еда',
            type=TransactionType.EXPENSE,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Category.objects.create(
                user=user,
                name='Еда',
                type=TransactionType.EXPENSE,
            )


class ModelStringRepresentationTest(TestCase):
    """Cover __str__ methods on the models."""

    fixtures: ClassVar[list[str]] = [
        'users.yaml',
        'finance_account.yaml',
    ]

    def test_category_str_returns_name(self) -> None:
        user = User.objects.get(pk=1)
        category = Category.objects.create(
            user=user,
            name='Кафе',
            type=TransactionType.EXPENSE,
        )
        self.assertEqual(str(category), 'Кафе')

    def test_transaction_str_uses_category(self) -> None:
        user = User.objects.get(pk=1)
        account = Account.objects.get(pk=1)
        category = Category.objects.create(
            user=user,
            name='Кафе',
            type=TransactionType.EXPENSE,
        )
        transaction_obj = Transaction.objects.create(
            user=user,
            account=account,
            category=category,
            amount=Decimal('100.00'),
            date=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
            type=TransactionType.EXPENSE,
        )
        self.assertEqual(str(transaction_obj), 'Кафе')
