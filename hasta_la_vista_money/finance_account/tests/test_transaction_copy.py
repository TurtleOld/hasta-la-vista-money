"""Copying a transaction prepares a new operation without posting it."""

from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

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


class TransactionCopyViewTest(TestCase):
    """Copy initiation must not create a financial movement."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username='copy-user')
        self.account = Account.objects.create(
            user=self.user,
            name_account='Debit',
            type_account=ACCOUNT_TYPE_DEBIT_CARD,
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.category = Category.objects.create(
            user=self.user,
            name='Food',
            type=TransactionType.EXPENSE,
        )
        self.original = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('125.50'),
            date=timezone.now(),
        )
        self.url = reverse(
            'finance_account:transaction_copy',
            args=[self.original.pk],
        )
        self.client.force_login(self.user)

    def test_copy_prefills_creation_without_changing_balance(self) -> None:
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 302)
        target = urlsplit(response['Location'])
        self.assertEqual(target.path, reverse('finances_create'))
        params = parse_qs(target.query)
        self.assertEqual(params['type'], ['expense'])
        self.assertEqual(params['category'], [str(self.category.pk)])
        self.assertEqual(params['account'], [str(self.account.pk)])
        self.assertEqual(params['amount'], ['125.50'])
        self.assertEqual(Transaction.objects.count(), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_cancel_and_reload_do_not_create_a_transaction(self) -> None:
        response = self.client.post(self.url)
        for _ in range(2):
            form_response = self.client.get(response['Location'])
            self.assertEqual(form_response.status_code, 200)
            self.assertTemplateUsed(
                form_response,
                'finance_account/create.html',
            )
        self.client.get(reverse('finances'))

        self.assertEqual(Transaction.objects.count(), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_save_creates_one_operation_with_edited_amount(self) -> None:
        for type_value, expected_balance in (
            (TransactionType.EXPENSE, Decimal('925.00')),
            (TransactionType.INCOME, Decimal('1000.00')),
        ):
            with self.subTest(type=type_value):
                self.category.type = type_value
                self.category.save()
                self.original.type = type_value
                self.original.save()
                count_before = Transaction.objects.count()
                response = self.client.post(self.url)
                params = parse_qs(urlsplit(response['Location']).query)
                response = self.client.post(
                    reverse('finances_create'),
                    {
                        'operation_type': params['type'][0],
                        'category': params['category'][0],
                        'account': params['account'][0],
                        'amount': '75.00',
                        'date': '2026-10-15T12:00',
                    },
                )

                self.assertRedirects(
                    response,
                    reverse('finances'),
                    fetch_redirect_response=False,
                )
                self.assertEqual(Transaction.objects.count(), count_before + 1)
                saved = Transaction.objects.latest('pk')
                self.assertEqual(saved.amount, Decimal('75.00'))
                self.assertEqual(saved.type, type_value)
                self.assertEqual(saved.account_id, self.account.pk)
                self.assertEqual(saved.category_id, self.category.pk)
                self.original.refresh_from_db()
                self.assertEqual(self.original.amount, Decimal('125.50'))
                self.account.refresh_from_db()
                self.assertEqual(self.account.balance, expected_balance)

    def test_invalid_save_does_not_create_a_transaction(self) -> None:
        self.client.post(self.url)
        self.client.post(
            reverse('finances_create'),
            {
                'operation_type': 'expense',
                'category': self.category.pk,
                'account': self.account.pk,
                'amount': '2000.00',
                'date': '2026-10-15T12:00',
            },
        )

        self.assertEqual(Transaction.objects.count(), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_foreign_or_missing_transaction_is_not_copied(self) -> None:
        other_user = User.objects.create_user(username='other-copy-user')
        self.client.force_login(other_user)
        self.assertEqual(self.client.post(self.url).status_code, 404)
        missing_url = reverse(
            'finance_account:transaction_copy',
            args=[self.original.pk + 1],
        )
        self.assertEqual(self.client.post(missing_url).status_code, 404)
        self.assertEqual(Transaction.objects.count(), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_copy_requires_login(self) -> None:
        self.client.logout()
        self.assertEqual(self.client.post(self.url).status_code, 302)
        self.assertEqual(Transaction.objects.count(), 1)
