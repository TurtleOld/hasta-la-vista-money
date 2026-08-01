from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.deposits.commands import CreateDepositCommand
from hasta_la_vista_money.deposits.models import Deposit
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
                'name': 'Летний вклад',
                'bank': 'SBERBANK',
                'currency': 'RUB',
                'balance': '75000.00',
                'opened_on': opened_on.isoformat(),
                'matures_on': matures_on.isoformat(),
                'annual_rate': '14.25',
            },
        )

        deposit = Deposit.objects.get(account__user=self.user)
        self.assertRedirects(response, deposit.get_absolute_url())

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
