"""Deleting or editing an operation returns to the same finances view."""

from decimal import Decimal
from urllib.parse import quote

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


class FinancesReturnStateTest(TestCase):
    """Filters and page survive delete and edit round trips."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username='return-user')
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
        self.transaction = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=timezone.now(),
        )
        self.finances_url = f'{reverse("finances")}?period=y&q=Food&page=1'
        self.client.force_login(self.user)

    def _delete(self, next_url: str) -> str:
        response = self.client.post(
            reverse(
                'finance_account:transaction_delete',
                args=[self.transaction.pk],
            ),
            {'next': next_url},
        )
        self.assertEqual(response.status_code, 302)
        return str(response['Location'])

    def test_delete_returns_to_filtered_list(self) -> None:
        self.assertEqual(self._delete(self.finances_url), self.finances_url)
        self.assertFalse(
            Transaction.objects.filter(pk=self.transaction.pk).exists(),
        )

    def test_delete_ignores_external_next(self) -> None:
        self.assertEqual(
            self._delete('https://evil.example/finance/'),
            reverse('finances'),
        )

    def test_list_links_carry_current_state(self) -> None:
        response = self.client.get(self.finances_url)

        self.assertContains(
            response,
            f'name="next" value="{self.finances_url.replace("&", "&amp;")}"',
        )
        edit_url = reverse(
            'finance_account:transaction_change',
            args=[self.transaction.pk],
        )
        self.assertContains(
            response,
            f'{edit_url}?next={quote(self.finances_url, safe="")}',
        )

    def test_edit_returns_to_filtered_list(self) -> None:
        edit_url = (
            reverse(
                'finance_account:transaction_change',
                args=[self.transaction.pk],
            )
            + f'?next={quote(self.finances_url, safe="")}'
        )

        page = self.client.get(edit_url)
        self.assertContains(
            page,
            f'href="{self.finances_url.replace("&", "&amp;")}"',
        )

        response = self.client.post(
            edit_url,
            {
                'type': TransactionType.EXPENSE,
                'category': self.category.pk,
                'account': self.account.pk,
                'date': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
                'amount': '150.00',
            },
        )
        self.assertRedirects(
            response,
            self.finances_url,
            fetch_redirect_response=False,
        )
