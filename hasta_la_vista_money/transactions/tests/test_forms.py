"""Tests for TransactionForm and CategoryForm validation."""

from decimal import Decimal
from typing import ClassVar

from django.test import TestCase

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.forms import (
    CategoryForm,
    TransactionForm,
)
from hasta_la_vista_money.transactions.models import Category, TransactionType
from hasta_la_vista_money.users.models import User


class TransactionFormTest(TestCase):
    fixtures: ClassVar[list[str]] = ['users.yaml']

    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = User.objects.get(pk=1)
        cls.account = Account.objects.create(
            user=cls.user,
            name_account='Карта',
            balance=Decimal('500.00'),
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

    def _build_form(self, **overrides: object) -> TransactionForm:
        data = {
            'type': TransactionType.EXPENSE,
            'category': self.expense_category.pk,
            'account': self.account.pk,
            'date': '2026-04-01T12:00',
            'amount': '100.00',
            **overrides,
        }
        return TransactionForm(
            data=data,
            category_queryset=Category.objects.filter(user=self.user),
            account_queryset=Account.objects.filter(user=self.user),
        )

    def test_valid_expense_within_balance(self) -> None:
        form = self._build_form()
        self.assertTrue(form.is_valid(), msg=form.errors)

    def test_naive_date_made_aware(self) -> None:
        form = self._build_form()
        self.assertTrue(form.is_valid())
        self.assertIsNotNone(form.cleaned_data['date'].tzinfo)

    def test_category_type_mismatch_rejected(self) -> None:
        form = self._build_form(category=self.income_category.pk)
        self.assertFalse(form.is_valid())
        self.assertIn('category', form.errors)

    def test_expense_exceeding_balance_rejected(self) -> None:
        form = self._build_form(amount='9999.00')
        self.assertFalse(form.is_valid())
        self.assertIn('account', form.errors)

    def test_income_does_not_check_balance(self) -> None:
        form = self._build_form(
            type=TransactionType.INCOME,
            category=self.income_category.pk,
            amount='9999.00',
        )
        self.assertTrue(form.is_valid(), msg=form.errors)


class CategoryFormTest(TestCase):
    fixtures: ClassVar[list[str]] = ['users.yaml']

    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = User.objects.get(pk=1)
        cls.income_parent = Category.objects.create(
            user=cls.user,
            name='Доходы',
            type=TransactionType.INCOME,
        )
        cls.expense_parent = Category.objects.create(
            user=cls.user,
            name='Дом',
            type=TransactionType.EXPENSE,
        )

    def test_create_with_matching_parent_valid(self) -> None:
        form = CategoryForm(
            data={
                'name': 'Аренда',
                'type': TransactionType.EXPENSE,
                'parent_category': self.expense_parent.pk,
            },
            category_queryset=Category.objects.filter(
                user=self.user,
                type=TransactionType.EXPENSE,
            ),
        )
        self.assertTrue(form.is_valid(), msg=form.errors)

    def test_parent_type_mismatch_rejected(self) -> None:
        form = CategoryForm(
            data={
                'name': 'Аренда',
                'type': TransactionType.EXPENSE,
                'parent_category': self.income_parent.pk,
            },
            category_queryset=Category.objects.filter(user=self.user),
        )
        self.assertFalse(form.is_valid())
        self.assertIn('parent_category', form.errors)

    def test_blank_parent_allowed(self) -> None:
        form = CategoryForm(
            data={
                'name': 'Без родителя',
                'type': TransactionType.INCOME,
                'parent_category': '',
            },
            category_queryset=Category.objects.filter(
                user=self.user,
                type=TransactionType.INCOME,
            ),
        )
        self.assertTrue(form.is_valid(), msg=form.errors)
