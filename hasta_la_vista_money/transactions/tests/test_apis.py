"""Tests for transaction REST API endpoints."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User


class TransactionAPITest(TestCase):
    fixtures: ClassVar[list[str]] = ['users.yaml']

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.account = Account.objects.create(
            user=self.user,
            name_account='Карта',
            balance=Decimal('500.00'),
            currency='RUB',
            type_account='D',
        )
        self.income_category = Category.objects.create(
            user=self.user,
            name='Зарплата',
            type=TransactionType.INCOME,
        )
        self.expense_category = Category.objects.create(
            user=self.user,
            name='Еда',
            type=TransactionType.EXPENSE,
        )
        self.income = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.income_category,
            amount=Decimal('1000.00'),
            date=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
            type=TransactionType.INCOME,
        )
        self.expense = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.expense_category,
            amount=Decimal('200.00'),
            date=datetime(2026, 2, 15, 10, 0, tzinfo=UTC),
            type=TransactionType.EXPENSE,
        )

    def test_by_group_returns_all_user_transactions(self) -> None:
        response = self.client.get(reverse('api:transactions:by_group'))
        self.assertEqual(response.status_code, 200)
        ids = {row['id'] for row in response.json()['results']}
        self.assertEqual(ids, {self.income.pk, self.expense.pk})

    def test_by_group_filters_by_type(self) -> None:
        response = self.client.get(
            reverse('api:transactions:by_group') + '?type=income',
        )
        results = response.json()['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], self.income.pk)

    def test_data_filters_by_date_range(self) -> None:
        response = self.client.get(
            reverse('api:transactions:data')
            + '?date_after=2026-02-01&date_before=2026-02-28',
        )
        results = response.json()['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], self.expense.pk)

    def test_retrieve_returns_serialized_transaction(self) -> None:
        response = self.client.get(
            reverse('api:transactions:retrieve', args=[self.income.pk]),
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['id'], self.income.pk)
        self.assertEqual(body['type'], 'income')
        self.assertEqual(body['category_name'], 'Зарплата')
        self.assertEqual(body['account_name'], 'Карта')

    def test_unauthenticated_request_rejected(self) -> None:
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse('api:transactions:by_group'))
        self.assertEqual(response.status_code, 401)
