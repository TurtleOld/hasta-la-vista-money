"""Tests for the TransactionFilter django-filter set."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar

from django.test import TestCase

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.filters import TransactionFilter
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User


class TransactionFilterTest(TestCase):
    fixtures: ClassVar[list[str]] = ['users.yaml']

    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = User.objects.get(pk=1)
        cls.account = Account.objects.create(
            user=cls.user,
            name_account='Карта',
            balance=Decimal('1000.00'),
            currency='RUB',
            type_account='D',
        )
        cls.income_category = Category.objects.create(
            user=cls.user,
            name='Зарплата',
            type=TransactionType.INCOME,
        )
        cls.expense_category = Category.objects.create(
            user=cls.user,
            name='Еда',
            type=TransactionType.EXPENSE,
        )
        cls.income = Transaction.objects.create(
            user=cls.user,
            account=cls.account,
            category=cls.income_category,
            amount=Decimal('1000.00'),
            date=datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
            type=TransactionType.INCOME,
        )
        cls.expense = Transaction.objects.create(
            user=cls.user,
            account=cls.account,
            category=cls.expense_category,
            amount=Decimal('200.00'),
            date=datetime(2026, 2, 15, 12, 0, tzinfo=UTC),
            type=TransactionType.EXPENSE,
        )

    def test_filter_user_categories_only(self) -> None:
        filterset = TransactionFilter(
            data={},
            queryset=Transaction.objects.all(),
            user=self.user,
        )
        category_qs = filterset.filters['category'].queryset
        self.assertEqual(
            set(category_qs),
            {self.income_category, self.expense_category},
        )

    def test_filter_by_type(self) -> None:
        filterset = TransactionFilter(
            data={'type': 'income'},
            queryset=Transaction.objects.all(),
            user=self.user,
        )
        ids = {row['id'] for row in filterset.qs}
        self.assertEqual(ids, {self.income.pk})

    def test_filter_by_account(self) -> None:
        other_account = Account.objects.create(
            user=self.user,
            name_account='Другой',
            balance=Decimal('0.00'),
            currency='RUB',
            type_account='D',
        )
        filterset = TransactionFilter(
            data={'account': other_account.pk},
            queryset=Transaction.objects.all(),
            user=self.user,
        )
        self.assertEqual(list(filterset.qs), [])

    def test_filter_qs_returns_dict_rows(self) -> None:
        filterset = TransactionFilter(
            data={},
            queryset=Transaction.objects.all(),
            users=[self.user],
        )
        rows = list(filterset.qs)
        self.assertEqual(len(rows), 2)
        self.assertIn('category__name', rows[0])
