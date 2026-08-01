from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.deposits.commands import CreateDepositCommand
from hasta_la_vista_money.deposits.models import Deposit, DepositPrincipalEvent
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.factories import UserFactory

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User


class DepositViewSmokeTests(TestCase):
    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.client.force_login(self.user)

    def test_user_creates_and_opens_term_deposit(self) -> None:
        opened_on = timezone.localdate()
        matures_on = opened_on + timedelta(days=184)
        response = self.client.post(
            reverse('deposits:create'),
            {
                'opening_method': 'opening_position',
                'name': 'Летний вклад',
                'bank': 'SBERBANK',
                'currency': 'RUB',
                'balance': '75000.00',
                'opened_on': opened_on.isoformat(),
                'matures_on': matures_on.isoformat(),
                'annual_rate': '14.25',
                'tracking_started_on': opened_on.isoformat(),
            },
        )

        deposit = Deposit.objects.get(account__user=self.user)
        self.assertRedirects(response, deposit.get_absolute_url())
        event = DepositPrincipalEvent.objects.get(deposit=deposit)
        self.assertEqual(
            event.type,
            DepositPrincipalEvent.Type.OPENING_POSITION,
        )
        self.assertEqual(event.effective_on, opened_on)

        list_response = self.client.get(reverse('deposits:list'))
        self.assertContains(list_response, 'Летний вклад')
        self.assertContains(list_response, '75 000.00')

        detail_response = self.client.get(deposit.get_absolute_url())
        self.assertContains(detail_response, 'Летний вклад')
        self.assertContains(detail_response, '14,25')
        self.assertContains(detail_response, matures_on.strftime('%d.%m.%Y'))
        self.assertContains(detail_response, 'Активен')

        accounts_response = self.client.get(reverse('finance_account:list'))
        self.assertContains(
            accounts_response,
            f'href="{deposit.get_absolute_url()}"',
        )

    def test_user_creates_deposit_funded_from_owned_account(self) -> None:
        """Funding from an owned account creates deposit, records FUNDING event,
        and preserves total balance."""
        source_account = Account.objects.create(
            user=self.user,
            name_account='Основной счёт',
            type_account=constants.ACCOUNT_TYPE_DEBIT,
            currency='RUB',
            balance=Decimal('100000.00'),
        )
        opened_on = timezone.localdate()

        response = self.client.post(
            reverse('deposits:create'),
            {
                'opening_method': 'funding',
                'source_account': source_account.pk,
                'name': 'Вклад переводом',
                'bank': 'SBERBANK',
                'currency': 'RUB',
                'balance': '60000.00',
                'opened_on': opened_on.isoformat(),
                'matures_on': (opened_on + timedelta(days=184)).isoformat(),
                'annual_rate': '14.25',
            },
        )

        deposit = Deposit.objects.get(account__user=self.user)
        self.assertRedirects(response, deposit.get_absolute_url())
        source_account.refresh_from_db()
        self.assertEqual(source_account.balance, Decimal('40000.00'))
        self.assertEqual(deposit.account.balance, Decimal('60000.00'))
        event = DepositPrincipalEvent.objects.get(deposit=deposit)
        self.assertEqual(event.type, DepositPrincipalEvent.Type.FUNDING)

    def test_funding_workflow_shows_currency_validation_error(self) -> None:
        """Currency mismatch between source account and deposit is caught and
        shown as a validation error without side effects."""
        source_account = Account.objects.create(
            user=self.user,
            name_account='Долларовый счёт',
            type_account=constants.ACCOUNT_TYPE_DEBIT,
            currency='USD',
            balance=Decimal('1000.00'),
        )
        opened_on = timezone.localdate()

        response = self.client.post(
            reverse('deposits:create'),
            {
                'opening_method': 'funding',
                'source_account': source_account.pk,
                'name': 'Рублёвый вклад',
                'bank': 'SBERBANK',
                'currency': 'RUB',
                'balance': '500.00',
                'opened_on': opened_on.isoformat(),
                'matures_on': (opened_on + timedelta(days=184)).isoformat(),
                'annual_rate': '14.25',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'Исходный счёт должен быть в валюте вклада.',
        )
        self.assertFalse(
            Deposit.objects.filter(account__user=self.user).exists(),
        )
        source_account.refresh_from_db()
        self.assertEqual(source_account.balance, Decimal('1000.00'))

    def test_user_cannot_open_another_users_deposit(self) -> None:
        other_user = cast('User', UserFactory())
        opened_on = timezone.localdate()
        deposit = (
            ApplicationContainer()
            .deposits.deposit_service()
            .create_term_deposit(
                CreateDepositCommand(
                    user=other_user,
                    name='Чужой вклад',
                    bank='SBERBANK',
                    currency='RUB',
                    balance=Decimal('10000.00'),
                    opened_on=opened_on,
                    matures_on=opened_on + timedelta(days=365),
                    annual_rate=Decimal('10.00'),
                ),
            )
        )

        response = self.client.get(deposit.get_absolute_url())

        self.assertEqual(response.status_code, 404)
