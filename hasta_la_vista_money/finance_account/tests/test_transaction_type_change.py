"""Editing an operation can turn an expense into an income and back."""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from hasta_la_vista_money.constants import ACCOUNT_TYPE_DEBIT_CARD
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User


class TransactionTypeChangeTest(TestCase):
    """The category chosen on the edit page decides the operation type."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username='type-user')
        self.account = Account.objects.create(
            user=self.user,
            name_account='Debit',
            type_account=ACCOUNT_TYPE_DEBIT_CARD,
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.food = Category.objects.create(
            user=self.user,
            name='Food',
            type=TransactionType.EXPENSE,
        )
        self.gift = Category.objects.create(
            user=self.user,
            name='Gift',
            type=TransactionType.INCOME,
        )
        # Balance 1000 already reflects this expense of 100.
        self.transaction = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.food,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=timezone.now(),
        )
        self.url = reverse(
            'finance_account:transaction_change',
            args=[self.transaction.pk],
        )
        self.client.force_login(self.user)

    def _post(self, category: Category) -> None:
        response = self.client.post(
            self.url,
            {
                'type': self.transaction.type,
                'category': category.pk,
                'account': self.account.pk,
                'date': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
                'amount': '100.00',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.transaction.refresh_from_db()
        self.account.refresh_from_db()

    def test_page_offers_categories_of_both_types(self) -> None:
        response = self.client.get(self.url)

        self.assertContains(response, '<optgroup label="Расходы">')
        self.assertContains(response, '<optgroup label="Доходы">')
        self.assertContains(response, f'value="{self.gift.pk}"')

    def test_income_category_turns_expense_into_income(self) -> None:
        self._post(self.gift)

        self.assertEqual(self.transaction.type, TransactionType.INCOME)
        self.assertEqual(self.transaction.category, self.gift)
        self.assertEqual(self.account.balance, Decimal('1200.00'))

    def test_expense_category_turns_income_back_into_expense(self) -> None:
        self._post(self.gift)
        self._post(self.food)

        self.assertEqual(self.transaction.type, TransactionType.EXPENSE)
        self.assertEqual(self.account.balance, Decimal('1000.00'))
