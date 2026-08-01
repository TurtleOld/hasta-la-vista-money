from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.deposits.commands import CreateDepositCommand
from hasta_la_vista_money.deposits.models import (
    Deposit,
    DepositPrincipalEvent,
    DepositTerm,
)
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
                'rate_kind': 'fixed',
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
                'rate_kind': 'fixed',
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
                'rate_kind': 'fixed',
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
                    rate_kind=DepositTerm.RateKind.FIXED,
                ),
            )
        )

        response = self.client.get(deposit.get_absolute_url())

        self.assertEqual(response.status_code, 404)


class DepositAddRatePeriodViewSmokeTests(TestCase):
    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.client.force_login(self.user)

    def _create_floating_deposit(self) -> Deposit:
        opened_on = timezone.localdate()
        matures_on = opened_on + timedelta(days=300)
        self.client.post(
            reverse('deposits:create'),
            {
                'opening_method': 'opening_position',
                'rate_kind': 'floating',
                'name': 'Плавающий вклад',
                'bank': 'SBERBANK',
                'currency': 'RUB',
                'balance': '50000.00',
                'opened_on': opened_on.isoformat(),
                'matures_on': matures_on.isoformat(),
                'annual_rate': '10.00',
                'tracking_started_on': opened_on.isoformat(),
            },
        )
        return Deposit.objects.get(account__user=self.user)

    def test_user_adds_floating_rate_period(self) -> None:
        deposit = self._create_floating_deposit()
        term = deposit.current_term

        response = self.client.post(
            reverse(
                'deposits:add-rate-period',
                kwargs={'pk': deposit.pk, 'term_id': term.pk},
            ),
            {
                'starts_on': (
                    timezone.localdate() + timedelta(days=30)
                ).isoformat(),
                'annual_rate': '11.75',
                'note': 'КС ЦБ РФ повышена',
            },
        )

        self.assertRedirects(response, deposit.get_absolute_url())
        term.refresh_from_db()
        self.assertEqual(term.rate_periods.count(), 2)

        detail_response = self.client.get(deposit.get_absolute_url())
        self.assertContains(detail_response, 'Плавающая')

    def test_other_user_cannot_add_rate_period(self) -> None:
        deposit = self._create_floating_deposit()
        term = deposit.current_term
        self.client.logout()
        other_user = cast('User', UserFactory())
        self.client.force_login(other_user)

        response = self.client.post(
            reverse(
                'deposits:add-rate-period',
                kwargs={'pk': deposit.pk, 'term_id': term.pk},
            ),
            {
                'starts_on': (
                    timezone.localdate() + timedelta(days=30)
                ).isoformat(),
                'annual_rate': '11.75',
                'note': 'попытка чужого пользователя',
            },
        )

        self.assertEqual(response.status_code, 404)


class DepositDetailFloatingRateDisplayTests(TestCase):
    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.client.force_login(self.user)

    def test_undefined_future_rate_is_shown_explicitly(self) -> None:
        """A floating term whose last rate period has already ended must
        show the rate as undefined, not silently continue the old rate."""
        service = ApplicationContainer().deposits.deposit_service()
        opened_on = timezone.localdate() - timedelta(days=60)
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=self.user,
                name='Вклад с истёкшим периодом',
                bank='SBERBANK',
                currency='RUB',
                balance=Decimal('20000.00'),
                opened_on=opened_on,
                matures_on=timezone.localdate() + timedelta(days=200),
                annual_rate=Decimal('9.00'),
                rate_kind=DepositTerm.RateKind.FLOATING,
            ),
        )
        term = deposit.current_term
        period = term.rate_periods.get()
        period.ends_on = timezone.localdate() - timedelta(days=1)
        period.save(update_fields=['ends_on'])

        response = self.client.get(deposit.get_absolute_url())

        self.assertContains(response, 'не определена')

    def test_undefined_future_rate_is_shown_explicitly_on_list(self) -> None:
        """The deposit list page must also show the rate as undefined
        for a floating term whose last rate period has already ended,
        instead of silently rendering a bare '%' sign."""
        service = ApplicationContainer().deposits.deposit_service()
        opened_on = timezone.localdate() - timedelta(days=60)
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=self.user,
                name='Вклад с истёкшим периодом (список)',
                bank='SBERBANK',
                currency='RUB',
                balance=Decimal('20000.00'),
                opened_on=opened_on,
                matures_on=timezone.localdate() + timedelta(days=200),
                annual_rate=Decimal('9.00'),
                rate_kind=DepositTerm.RateKind.FLOATING,
            ),
        )
        term = deposit.current_term
        period = term.rate_periods.get()
        period.ends_on = timezone.localdate() - timedelta(days=1)
        period.save(update_fields=['ends_on'])

        response = self.client.get(reverse('deposits:list'))

        self.assertContains(response, 'не определена')
