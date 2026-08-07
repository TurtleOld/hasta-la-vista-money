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
    DepositCapitalizationEvent,
    DepositInterestForecast,
    DepositPrincipalEvent,
    DepositTerm,
)
from hasta_la_vista_money.finance_account.models import Account, Bank
from hasta_la_vista_money.users.factories import UserFactory

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User


def _sberbank() -> Bank:
    bank, _ = Bank.objects.get_or_create(
        code='SBERBANK',
        defaults={'name': 'Сбербанк', 'is_system': True},
    )
    return bank


class DepositViewSmokeTests(TestCase):
    def test_overview_separates_archived_and_groups_assets_and_liquidity(
        self,
    ) -> None:
        service = ApplicationContainer().deposits.deposit_service()
        today = timezone.localdate()
        Account.objects.create(
            user=self.user,
            name_account='Долларовый счёт',
            type_account=constants.ACCOUNT_TYPE_DEBIT,
            currency='USD',
            balance=Decimal('25.00'),
        )
        Account.objects.create(
            user=self.user,
            name_account='Долларовый кредит',
            type_account=constants.ACCOUNT_TYPE_CREDIT,
            currency='USD',
            balance=Decimal('500.00'),
        )
        active = service.create_term_deposit(
            CreateDepositCommand(
                user=self.user,
                name='Активный вклад',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('1000.00'),
                opened_on=today,
                matures_on=today + timedelta(days=90),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        active_term = active.current_term
        active_term.withdrawal_allowed = True
        active_term.minimum_balance = Decimal('700.00')
        active_term.save()
        forecast = DepositInterestForecast.objects.create(
            term=active_term,
            payout_on=today + timedelta(days=30),
            amount=Decimal('10.00'),
            period_starts_on=today,
            period_ends_on=today + timedelta(days=29),
        )
        archived = service.create_term_deposit(
            CreateDepositCommand(
                user=self.user,
                name='Архивный вклад',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('0.00'),
                opened_on=today - timedelta(days=180),
                matures_on=today - timedelta(days=90),
                annual_rate=Decimal('10.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        archived.account.archived_at = timezone.now()
        archived.account.save(update_fields=['archived_at'])
        archived.current_term.closed_on = today - timedelta(days=90)
        archived.current_term.save(update_fields=['closed_on'])

        response = self.client.get(reverse('deposits:list'))

        self.assertEqual(list(response.context['active_deposits']), [active])
        self.assertEqual(
            list(response.context['archived_deposits']),
            [archived],
        )
        self.assertEqual(
            response.context['overview_by_currency'],
            {
                'RUB': {
                    'assets': Decimal('1000.00'),
                    'liquidity': Decimal('300.00'),
                },
                'USD': {
                    'assets': Decimal('25.00'),
                    'liquidity': Decimal('25.00'),
                },
            },
        )
        self.assertContains(response, 'Активные вклады')
        self.assertContains(response, 'Архив')
        self.assertContains(response, 'Ликвидная сумма')
        self.assertContains(response, 'Ближайшая выплата')
        self.assertContains(response, 'Дата окончания')
        self.assertContains(response, forecast.payout_on.strftime('%d.%m.%Y'))

    def test_user_reverses_event_and_sees_reason_in_history(self) -> None:
        service = ApplicationContainer().deposits.deposit_service()
        opened_on = timezone.localdate()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=self.user,
                name='Вклад с исправлением',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=opened_on,
                matures_on=opened_on + timedelta(days=184),
                annual_rate=Decimal('14.25'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        event = deposit.principal_events.get()

        response = self.client.post(
            reverse(
                'deposits:reverse-event',
                kwargs={
                    'pk': deposit.pk,
                    'event_kind': 'principal',
                    'event_id': event.pk,
                },
            ),
            {
                'reason': 'Начальная позиция указана ошибочно.',
                'reversed_on': opened_on.isoformat(),
            },
        )

        self.assertRedirects(response, deposit.get_absolute_url())
        detail = self.client.get(deposit.get_absolute_url())
        self.assertContains(detail, 'Начальная позиция')
        self.assertContains(detail, 'Аннулирование')
        self.assertContains(detail, 'Начальная позиция указана ошибочно.')

    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.client.force_login(self.user)
        self.sberbank_pk = _sberbank().pk

    def test_user_creates_and_opens_term_deposit(self) -> None:
        opened_on = timezone.localdate()
        matures_on = opened_on + timedelta(days=184)
        response = self.client.post(
            reverse('deposits:create'),
            {
                'opening_method': 'opening_position',
                'rate_kind': 'fixed',
                'name': 'Летний вклад',
                'bank': self.sberbank_pk,
                'currency': 'RUB',
                'balance': '75000.00',
                'opened_on': opened_on.isoformat(),
                'matures_on': matures_on.isoformat(),
                'annual_rate': '14.25',
                'tracking_started_on': opened_on.isoformat(),
                'interest_payout_destination': 'external',
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
        self.assertEqual(
            deposit.current_term.interest_payout_destination,
            DepositTerm.PayoutDestination.EXTERNAL,
        )

        list_response = self.client.get(reverse('deposits:list'))
        self.assertContains(list_response, 'Летний вклад')
        self.assertContains(list_response, '75 000.00')

        detail_response = self.client.get(deposit.get_absolute_url())
        self.assertContains(detail_response, 'Летний вклад')
        self.assertContains(detail_response, '14,25')
        self.assertContains(detail_response, matures_on.strftime('%d.%m.%Y'))
        self.assertContains(detail_response, 'Активен')
        capitalize_form = detail_response.context['capitalize_form']
        self.assertEqual(
            capitalize_form.initial['destination'],
            DepositTerm.PayoutDestination.EXTERNAL,
        )

        accounts_response = self.client.get(reverse('finance_account:list'))
        self.assertContains(
            accounts_response,
            f'href="{deposit.get_absolute_url()}"',
        )

    def test_user_adds_personal_bank_from_create_form_without_losing_terms(
        self,
    ) -> None:
        """Adding a personal bank mid-form keeps the entered contract terms.

        The deposit form renders a quick-add control for the bank field
        (see deposit_form.html + finance_account:quick_bank) that lets the
        browser create a personal bank via AJAX and select it without a
        page reload. This smoke-tests the two HTTP calls that flow
        performs, in order, and confirms the deposit is created against
        the freshly added bank.
        """
        form_response = self.client.get(reverse('deposits:create'))
        self.assertContains(form_response, 'data-qb-root')
        self.assertContains(
            form_response,
            reverse('finance_account:quick_bank'),
        )

        quick_add_response = self.client.post(
            reverse('finance_account:quick_bank'),
            {'name': 'Мой карманный банк'},
        )
        self.assertEqual(quick_add_response.status_code, constants.SUCCESS_CODE)
        payload = quick_add_response.json()
        self.assertTrue(payload['ok'])
        personal_bank = Bank.objects.get(pk=payload['id'])
        self.assertFalse(personal_bank.is_system)

        opened_on = timezone.localdate()
        matures_on = opened_on + timedelta(days=184)
        create_response = self.client.post(
            reverse('deposits:create'),
            {
                'opening_method': 'opening_position',
                'rate_kind': 'fixed',
                'name': 'Вклад в своём банке',
                'bank': personal_bank.pk,
                'currency': 'RUB',
                'balance': '50000.00',
                'opened_on': opened_on.isoformat(),
                'matures_on': matures_on.isoformat(),
                'annual_rate': '12.00',
                'tracking_started_on': opened_on.isoformat(),
            },
        )

        deposit = Deposit.objects.get(account__user=self.user)
        self.assertRedirects(create_response, deposit.get_absolute_url())
        self.assertEqual(deposit.bank, personal_bank)
        self.assertEqual(deposit.account.bank, personal_bank)

    def test_user_withdraws_liquid_amount_from_detail_card(self) -> None:
        """The detail workflow transfers the permitted liquid principal."""
        destination = Account.objects.create(
            user=self.user,
            name_account='Основной счёт',
            type_account=constants.ACCOUNT_TYPE_DEBIT,
            currency='RUB',
            balance=Decimal('0.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        opened_on = timezone.localdate()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=self.user,
                name='Вклад для снятия',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('1000.00'),
                opened_on=opened_on,
                matures_on=opened_on + timedelta(days=184),
                annual_rate=Decimal('14.25'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        term = deposit.current_term
        term.withdrawal_allowed = True
        term.maximum_withdrawal_amount = Decimal('300.00')
        term.minimum_balance = Decimal('700.00')
        term.save()

        detail_response = self.client.get(deposit.get_absolute_url())
        self.assertContains(detail_response, 'Ликвидная сумма')
        self.assertContains(detail_response, '300.00')

        response = self.client.post(
            reverse('deposits:withdraw', args=[deposit.pk]),
            {
                'destination_account': destination.pk,
                'amount': '300.00',
                'effective_on': opened_on.isoformat(),
            },
        )

        self.assertRedirects(response, deposit.get_absolute_url())
        deposit.account.refresh_from_db()
        destination.refresh_from_db()
        self.assertEqual(deposit.account.balance, Decimal('700.00'))
        self.assertEqual(destination.balance, Decimal('300.00'))

    def test_user_tops_up_deposit_from_detail_card(self) -> None:
        source = Account.objects.create(
            user=self.user,
            name_account='Основной счёт',
            type_account=constants.ACCOUNT_TYPE_DEBIT,
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        opened_on = timezone.localdate()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=self.user,
                name='Вклад для пополнения',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=opened_on,
                matures_on=opened_on + timedelta(days=184),
                annual_rate=Decimal('14.25'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        term = deposit.current_term
        term.top_up_allowed = True
        term.save(update_fields=['top_up_allowed'])

        detail_response = self.client.get(deposit.get_absolute_url())
        self.assertContains(detail_response, 'Пополнить вклад')

        response = self.client.post(
            reverse('deposits:top-up', args=[deposit.pk]),
            {
                'source_account': source.pk,
                'amount': '250.00',
                'effective_on': opened_on.isoformat(),
            },
        )

        self.assertRedirects(response, deposit.get_absolute_url())
        source.refresh_from_db()
        deposit.account.refresh_from_db()
        self.assertEqual(source.balance, Decimal('750.00'))
        self.assertEqual(deposit.account.balance, Decimal('750.00'))

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
                'bank': self.sberbank_pk,
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
                'bank': self.sberbank_pk,
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
                    bank=_sberbank(),
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
        self.sberbank_pk = _sberbank().pk

    def _create_floating_deposit(self) -> Deposit:
        opened_on = timezone.localdate()
        matures_on = opened_on + timedelta(days=300)
        self.client.post(
            reverse('deposits:create'),
            {
                'opening_method': 'opening_position',
                'rate_kind': 'floating',
                'name': 'Плавающий вклад',
                'bank': self.sberbank_pk,
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
                bank=_sberbank(),
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
                bank=_sberbank(),
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


class DepositRecalculateForecastViewSmokeTests(TestCase):
    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.client.force_login(self.user)
        self.sberbank_pk = _sberbank().pk

    def _create_deposit(self) -> Deposit:
        service = ApplicationContainer().deposits.deposit_service()
        opened_on = timezone.localdate()
        deposit: Deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=self.user,
                name='Вклад для прогноза',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('100000.00'),
                opened_on=opened_on,
                matures_on=opened_on + timedelta(days=365),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        return deposit

    def test_user_recalculates_forecast_and_sees_it_on_the_card(self) -> None:
        deposit = self._create_deposit()
        term = deposit.current_term

        response = self.client.post(
            reverse(
                'deposits:recalculate-forecast',
                kwargs={'pk': deposit.pk, 'term_id': term.pk},
            ),
        )

        self.assertRedirects(response, deposit.get_absolute_url())
        self.assertTrue(
            DepositInterestForecast.objects.filter(term=term).exists(),
        )
        detail_response = self.client.get(deposit.get_absolute_url())
        self.assertContains(detail_response, 'Ожидаемые выплаты процентов')
        self.assertContains(detail_response, 'Способ выплаты')
        self.assertContains(detail_response, 'В конце срока')

    def test_other_user_cannot_recalculate_forecast(self) -> None:
        deposit = self._create_deposit()
        term = deposit.current_term
        self.client.logout()
        other_user = cast('User', UserFactory())
        self.client.force_login(other_user)

        response = self.client.post(
            reverse(
                'deposits:recalculate-forecast',
                kwargs={'pk': deposit.pk, 'term_id': term.pk},
            ),
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            DepositInterestForecast.objects.filter(term=term).exists(),
        )

    def test_user_selects_custom_schedule_and_recalculates_forecast(
        self,
    ) -> None:
        """End-to-end: the user picks Actual/365, a custom payout
        schedule, and a business-day roll on the create form; the
        resulting term carries those choices into the forecast."""
        opened_on = timezone.localdate()
        matures_on = opened_on + timedelta(days=120)
        first_payout = (opened_on + timedelta(days=40)).strftime('%d/%m/%Y')

        response = self.client.post(
            reverse('deposits:create'),
            {
                'opening_method': 'opening_position',
                'rate_kind': 'fixed',
                'day_count_convention': 'actual_365',
                'payout_schedule_kind': 'custom',
                'custom_payout_dates': first_payout,
                'business_day_convention': 'following',
                'name': 'Вклад с индивидуальным расписанием',
                'bank': self.sberbank_pk,
                'currency': 'RUB',
                'balance': '40000.00',
                'opened_on': opened_on.isoformat(),
                'matures_on': matures_on.isoformat(),
                'annual_rate': '13.00',
                'tracking_started_on': opened_on.isoformat(),
            },
        )

        deposit = Deposit.objects.get(account__user=self.user)
        self.assertRedirects(response, deposit.get_absolute_url())
        term = deposit.current_term
        self.assertEqual(
            term.day_count_convention,
            DepositTerm.DayCountConvention.ACTUAL_365,
        )
        self.assertEqual(
            term.payout_schedule_kind,
            DepositTerm.PayoutScheduleKind.CUSTOM,
        )
        self.assertEqual(term.payout_schedule_dates.count(), 1)

        recalculate_response = self.client.post(
            reverse(
                'deposits:recalculate-forecast',
                kwargs={'pk': deposit.pk, 'term_id': term.pk},
            ),
        )

        self.assertRedirects(recalculate_response, deposit.get_absolute_url())
        forecasts = DepositInterestForecast.objects.filter(term=term)
        self.assertEqual(forecasts.count(), 2)
        self.assertTrue(
            any(line.period_ends_on == matures_on for line in forecasts),
        )


class CapitalizeInterestSmokeTests(TestCase):
    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.client.force_login(self.user)
        service = ApplicationContainer().deposits.deposit_service()
        self.deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=self.user,
                name='Вклад для капитализации',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('100000.00'),
                opened_on=timezone.localdate() - timedelta(days=30),
                matures_on=timezone.localdate() + timedelta(days=335),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )

    def test_capitalize_increases_balance_and_creates_event(self) -> None:
        balance_before = self.deposit.account.balance
        response = self.client.post(
            reverse('deposits:capitalize', kwargs={'pk': self.deposit.pk}),
            {
                'gross': '6000.00',
                'withholding': '780.00',
                'net': '5220.00',
                'posting_on': timezone.localdate().isoformat(),
                'value_on': timezone.localdate().isoformat(),
                'reason': 'Плановая капитализация.',
            },
        )

        self.assertRedirects(response, self.deposit.get_absolute_url())
        self.deposit.account.refresh_from_db()
        self.assertEqual(
            self.deposit.account.balance,
            balance_before + Decimal('5220.00'),
        )
        event = DepositCapitalizationEvent.objects.get(
            deposit=self.deposit,
        )
        self.assertEqual(event.gross, Decimal('6000.00'))
        self.assertEqual(event.withholding, Decimal('780.00'))
        self.assertEqual(event.net, Decimal('5220.00'))
        self.assertEqual(event.reason, 'Плановая капитализация.')

    def test_capitalize_rejects_inconsistent_amounts(self) -> None:
        response = self.client.post(
            reverse('deposits:capitalize', kwargs={'pk': self.deposit.pk}),
            {
                'gross': '6000.00',
                'withholding': '780.00',
                'net': '5000.00',
                'posting_on': timezone.localdate().isoformat(),
                'value_on': timezone.localdate().isoformat(),
                'reason': 'Неверные суммы.',
            },
        )

        self.assertRedirects(response, self.deposit.get_absolute_url())
        self.deposit.account.refresh_from_db()
        self.assertEqual(self.deposit.account.balance, Decimal('100000.00'))
        self.assertFalse(
            DepositCapitalizationEvent.objects.filter(
                deposit=self.deposit,
            ).exists(),
        )

    def test_detail_page_includes_capitalize_form(self) -> None:
        response = self.client.get(
            reverse('deposits:detail', kwargs={'pk': self.deposit.pk}),
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Подтвердить выплату процентов', content)

    def test_user_pays_interest_to_owned_account(self) -> None:
        destination = Account.objects.create(
            user=self.user,
            name_account='Карта для процентов',
            currency='RUB',
            balance=Decimal('1000.00'),
        )

        response = self.client.post(
            reverse('deposits:capitalize', kwargs={'pk': self.deposit.pk}),
            {
                'gross': '6000.00',
                'withholding': '780.00',
                'net': '5220.00',
                'posting_on': timezone.localdate().isoformat(),
                'value_on': timezone.localdate().isoformat(),
                'reason': 'Выплата на карту.',
                'destination': 'internal_account',
                'destination_account': str(destination.pk),
            },
        )

        self.assertRedirects(response, self.deposit.get_absolute_url())
        destination.refresh_from_db()
        self.assertEqual(destination.balance, Decimal('6220.00'))
        detail = self.client.get(self.deposit.get_absolute_url())
        content = detail.content.decode()
        self.assertIn('На собственный счёт', content)
        self.assertIn('Карта для процентов', content)


class CloseMaturedDepositSmokeTests(TestCase):
    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.client.force_login(self.user)
        service = ApplicationContainer().deposits.deposit_service()
        self.deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=self.user,
                name='Вклад к закрытию',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('100000.00'),
                opened_on=timezone.localdate() - timedelta(days=365),
                matures_on=timezone.localdate(),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        self.destination = Account.objects.create(
            user=self.user,
            name_account='Счёт возврата',
            currency='RUB',
            balance=Decimal('1000.00'),
        )

    def test_user_closes_matured_deposit_from_detail_card(self) -> None:
        detail_before = self.client.get(self.deposit.get_absolute_url())
        self.assertContains(detail_before, 'Закрыть вклад')

        response = self.client.post(
            reverse('deposits:close', kwargs={'pk': self.deposit.pk}),
            {
                'destination': 'internal_account',
                'destination_account': str(self.destination.pk),
                'principal': '100000.00',
                'gross': '12000.00',
                'withholding': '1560.00',
                'net': '10440.00',
                'posting_on': timezone.localdate().isoformat(),
                'value_on': timezone.localdate().isoformat(),
            },
        )

        self.assertRedirects(response, self.deposit.get_absolute_url())
        self.destination.refresh_from_db()
        self.assertEqual(self.destination.balance, Decimal('111440.00'))
        detail_after = self.client.get(self.deposit.get_absolute_url())
        self.assertContains(detail_after, 'Закрыт')
        self.assertContains(detail_after, 'Плановое закрытие')
        self.assertNotContains(detail_after, 'Пополнить вклад')
        self.assertNotContains(detail_after, 'Снять тело вклада')


class RenewMaturedDepositSmokeTests(TestCase):
    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.client.force_login(self.user)
        service = ApplicationContainer().deposits.deposit_service()
        self.deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=self.user,
                name='Продлеваемый вклад',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('100000.00'),
                opened_on=timezone.localdate() - timedelta(days=365),
                matures_on=timezone.localdate(),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )

    def test_user_renews_matured_deposit_and_sees_term_history(self) -> None:
        old_term = self.deposit.current_term
        detail_before = self.client.get(self.deposit.get_absolute_url())
        self.assertContains(detail_before, 'Пролонгировать вклад')
        renew_url = reverse('deposits:renew', args=[self.deposit.pk])
        form_response = self.client.get(renew_url)
        self.assertEqual(form_response.status_code, 200)
        self.assertEqual(
            form_response.context['form'].initial['annual_rate'],
            Decimal('12.00'),
        )
        opened_on = timezone.localdate() + timedelta(days=1)
        matures_on = opened_on + timedelta(days=180)

        response = self.client.post(
            renew_url,
            {
                'rate_kind': 'fixed',
                'opened_on': opened_on.isoformat(),
                'matures_on': matures_on.isoformat(),
                'annual_rate': '10.50',
                'payout_schedule_kind': 'maturity',
            },
        )

        self.assertRedirects(response, self.deposit.get_absolute_url())
        old_term.refresh_from_db()
        self.assertFalse(old_term.is_current)
        new_term = self.deposit.current_term
        self.assertEqual(new_term.opened_on, opened_on)
        self.assertTrue(new_term.interest_forecasts.exists())
        detail_after = self.client.get(self.deposit.get_absolute_url())
        self.assertContains(detail_after, 'История сроков')
        self.assertContains(detail_after, 'Текущий срок')
        self.assertContains(detail_after, 'Завершённый срок')
        self.assertContains(
            detail_after,
            old_term.opened_on.strftime('%d.%m.%Y'),
        )
        self.assertContains(detail_after, opened_on.strftime('%d.%m.%Y'))

    def test_other_user_cannot_renew_deposit(self) -> None:
        self.client.logout()
        self.client.force_login(cast('User', UserFactory()))

        response = self.client.get(
            reverse('deposits:renew', args=[self.deposit.pk]),
        )

        self.assertEqual(response.status_code, 404)

    def test_zero_balance_hides_and_rejects_renewal(self) -> None:
        Account.objects.filter(pk=self.deposit.account.pk).update(
            balance=Decimal(),
        )

        detail_response = self.client.get(self.deposit.get_absolute_url())
        renew_response = self.client.get(
            reverse('deposits:renew', args=[self.deposit.pk]),
        )

        self.assertNotContains(detail_response, 'Пролонгировать вклад')
        self.assertEqual(renew_response.status_code, 404)
