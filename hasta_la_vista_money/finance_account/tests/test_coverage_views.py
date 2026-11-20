"""Owner-facing coverage confirmation and account-page warning."""

from datetime import date
from decimal import Decimal
from typing import Any

from django.test import Client, TestCase
from django.urls import reverse

from hasta_la_vista_money.finance_account.models import (
    Account,
    AccountCoverageConfirmation,
)
from hasta_la_vista_money.users.models import User


class AccountCoverageViewTest(TestCase):
    """The owner confirms coverage without moving money."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='coverage-view',
            password='test-only-password',  # nosec B106
        )
        self.other = User.objects.create_user(username='coverage-view-other')
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной счёт',
            currency='RUB',
            balance=Decimal('100.00'),
        )
        self.foreign = Account.objects.create(
            user=self.other,
            name_account='Чужой счёт',
            currency='RUB',
        )
        self.client = Client()
        self.client.force_login(self.user)

    def _post(self, **overrides: object) -> Any:
        data: dict[str, object] = {
            'account': self.account.pk,
            'period_start': '2026-01-01',
            'period_end': '2026-01-31',
            'source': AccountCoverageConfirmation.Source.BANK,
            'statement_upload': '',
        }
        data.update(overrides)
        return self.client.post(
            reverse('finance_account:coverage_confirm'),
            data,
        )

    def test_owner_confirms_inclusive_coverage(self):
        response = self._post()

        self.assertEqual(response.status_code, 302)
        confirmation = AccountCoverageConfirmation.objects.get()
        self.assertEqual(confirmation.account, self.account)
        self.assertEqual(confirmation.period_start, date(2026, 1, 1))
        self.assertEqual(confirmation.period_end, date(2026, 1, 31))
        self.assertEqual(confirmation.confirmed_by, self.user)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('100.00'))

    def test_manual_coverage_is_allowed_for_bank_debit(self):
        response = self._post(
            source=AccountCoverageConfirmation.Source.MANUAL,
        )

        self.assertEqual(response.status_code, 302)
        confirmation = AccountCoverageConfirmation.objects.get()
        self.assertEqual(
            confirmation.source,
            AccountCoverageConfirmation.Source.MANUAL,
        )

    def test_foreign_account_is_not_confirmed(self):
        response = self._post(account=self.foreign.pk)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(AccountCoverageConfirmation.objects.exists())

    def test_reversed_period_is_not_confirmed(self):
        response = self._post(
            period_start='2026-02-01',
            period_end='2026-01-01',
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(AccountCoverageConfirmation.objects.exists())

    def test_account_page_shows_coverage_panel(self):
        response = self.client.get(reverse('finance_account:list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Покрытие периода')
        self.assertContains(response, 'Подтвердить покрытие')
        self.assertContains(response, 'Разрывы:')
