from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from django.forms import ChoiceField, DateField, DateInput, ModelChoiceField
from django.test import TestCase
from django.utils import translation

from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.deposits.commands import CreateDepositCommand
from hasta_la_vista_money.deposits.forms import (
    AddFloatingRatePeriodForm,
    CapitalizeInterestForm,
    CorrectPayoutScheduleForm,
    CreateDepositForm,
    RenewDepositForm,
    TopUpDepositForm,
)
from hasta_la_vista_money.deposits.models import Deposit, DepositTerm
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


class TopUpDepositFormLabelTests(TestCase):
    def test_labels_stay_russian_under_english_locale(self) -> None:
        user = UserFactory()
        with translation.override('en'):
            form = TopUpDepositForm(user=user, currency='RUB')
            self.assertEqual(
                str(form.fields['source_account'].label),
                'Счёт списания',
            )
            self.assertEqual(
                str(form.fields['amount'].label),
                'Сумма пополнения',
            )


class CreateDepositFormTests(TestCase):
    def test_date_fields_use_project_date_widget(self) -> None:
        form = CreateDepositForm()

        for field_name in ('opened_on', 'matures_on'):
            with self.subTest(field_name=field_name):
                field = form.fields[field_name]
                self.assertIsInstance(field, DateField)
                self.assertIsInstance(field.widget, DateInput)
                self.assertEqual(
                    field.widget.format,
                    constants.HTML5_DATE_INPUT_FORMAT,
                )
                self.assertEqual(field.widget.attrs['data-flatpickr'], 'true')
                self.assertEqual(field.widget.attrs['lang'], 'ru-RU')
                self.assertEqual(
                    field.widget.attrs['placeholder'],
                    'ДД.ММ.ГГГГ',
                )

    def test_funding_workflow_requires_owned_source_account(self) -> None:
        """Source account queryset includes only the user's own
        non-deposit accounts."""
        user = cast('User', UserFactory())
        other_user = cast('User', UserFactory())
        source_account = Account.objects.create(
            user=user,
            name_account='Основной счёт',
            type_account=constants.ACCOUNT_TYPE_DEBIT,
            currency='RUB',
            balance='100000.00',
        )
        foreign_account = Account.objects.create(
            user=other_user,
            name_account='Чужой счёт',
            type_account=constants.ACCOUNT_TYPE_DEBIT,
            currency='RUB',
            balance='100000.00',
        )

        form = CreateDepositForm(
            user=user,
            data={
                'name': 'Новый вклад',
                'bank': _sberbank().pk,
                'currency': 'RUB',
                'balance': '50000.00',
                'opened_on': '2026-08-01',
                'matures_on': '2027-02-01',
                'annual_rate': '15.50',
                'opening_method': 'funding',
                'rate_kind': 'fixed',
                'source_account': source_account.pk,
            },
        )

        self.assertTrue(form.is_valid(), form.errors)
        source_field = cast(
            'ModelChoiceField[Account]',
            form.fields['source_account'],
        )
        source_queryset = source_field.queryset
        if source_queryset is None:
            self.fail('Source account queryset was not configured.')
        self.assertIn(source_account, source_queryset)
        self.assertNotIn(foreign_account, source_queryset)

    def test_opening_position_workflow_requires_tracking_date(self) -> None:
        """Opening-position form is invalid when tracking_started_on
        is missing."""
        user = cast('User', UserFactory())
        form = CreateDepositForm(
            user=user,
            data={
                'name': 'Действующий вклад',
                'bank': _sberbank().pk,
                'currency': 'RUB',
                'balance': '50000.00',
                'opened_on': '2026-06-01',
                'matures_on': '2027-02-01',
                'annual_rate': '15.50',
                'opening_method': 'opening_position',
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn('tracking_started_on', form.errors)


class CreateDepositFormForecastTermsTests(TestCase):
    def _base_data(self) -> dict[str, object]:
        return {
            'name': 'Вклад с прогнозом',
            'bank': _sberbank().pk,
            'currency': 'RUB',
            'balance': '50000.00',
            'opened_on': '2026-06-01',
            'matures_on': '2027-02-01',
            'annual_rate': '15.50',
            'opening_method': 'opening_position',
            'tracking_started_on': '2026-06-01',
            'rate_kind': 'fixed',
        }

    def test_forecast_fields_default_when_omitted(self) -> None:
        """Omitting the new forecast-terms fields (e.g. programmatic POST)
        falls back to the previous fixed behaviour instead of failing
        validation."""
        form = CreateDepositForm(data=self._base_data())

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data['day_count_convention'],
            DepositTerm.DayCountConvention.ACTUAL_ACTUAL,
        )
        self.assertEqual(
            form.cleaned_data['payout_schedule_kind'],
            DepositTerm.PayoutScheduleKind.MATURITY,
        )
        self.assertEqual(
            form.cleaned_data['business_day_convention'],
            DepositTerm.BusinessDayConvention.NONE,
        )
        self.assertEqual(form.cleaned_data['custom_payout_dates'], [])

    def test_user_can_select_actual_365_and_monthly_schedule(self) -> None:
        data = self._base_data()
        data['day_count_convention'] = 'actual_365'
        data['payout_schedule_kind'] = 'monthly'
        data['business_day_convention'] = 'following'

        form = CreateDepositForm(data=data)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data['day_count_convention'],
            DepositTerm.DayCountConvention.ACTUAL_365,
        )
        self.assertEqual(
            form.cleaned_data['payout_schedule_kind'],
            DepositTerm.PayoutScheduleKind.MONTHLY,
        )
        self.assertEqual(
            form.cleaned_data['business_day_convention'],
            DepositTerm.BusinessDayConvention.FOLLOWING,
        )

    def test_custom_schedule_requires_at_least_one_date(self) -> None:
        data = self._base_data()
        data['payout_schedule_kind'] = 'custom'

        form = CreateDepositForm(data=data)

        self.assertFalse(form.is_valid())
        self.assertIn('custom_payout_dates', form.errors)

    def test_custom_schedule_parses_comma_and_newline_separated_dates(
        self,
    ) -> None:
        data = self._base_data()
        data['payout_schedule_kind'] = 'custom'
        data['custom_payout_dates'] = '15/07/2026,\n01/09/2026'

        form = CreateDepositForm(data=data)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data['custom_payout_dates'],
            [date(2026, 7, 15), date(2026, 9, 1)],
        )

    def test_custom_schedule_rejects_unparseable_date(self) -> None:
        data = self._base_data()
        data['payout_schedule_kind'] = 'custom'
        data['custom_payout_dates'] = 'not-a-date'

        form = CreateDepositForm(data=data)

        self.assertFalse(form.is_valid())
        self.assertIn('custom_payout_dates', form.errors)


class CreateDepositFormRateKindTests(TestCase):
    def test_rate_kind_field_offers_fixed_and_floating(self) -> None:
        form = CreateDepositForm()
        rate_kind_field = cast('ChoiceField', form.fields['rate_kind'])
        choices = cast(
            'list[tuple[str, str]]',
            rate_kind_field.choices,
        )
        choice_values = [choice[0] for choice in choices]
        self.assertIn(DepositTerm.RateKind.FIXED, choice_values)
        self.assertIn(DepositTerm.RateKind.FLOATING, choice_values)


class AddFloatingRatePeriodFormTests(TestCase):
    def test_requires_non_blank_note(self) -> None:
        form = AddFloatingRatePeriodForm(
            data={
                'starts_on': '2026-03-01',
                'annual_rate': '11.50',
                'note': '   ',
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn('note', form.errors)

    def test_valid_with_note_and_positive_rate(self) -> None:
        form = AddFloatingRatePeriodForm(
            data={
                'starts_on': '2026-03-01',
                'annual_rate': '11.50',
                'note': 'КС ЦБ РФ + 2%',
            },
        )

        self.assertTrue(form.is_valid(), form.errors)


class RenewDepositFormTests(TestCase):
    def test_initial_values_preserve_previous_terms_for_explicit_editing(
        self,
    ) -> None:
        user = cast('User', UserFactory())
        account = Account.objects.create(
            user=user,
            name_account='Вклад',
            type_account=constants.ACCOUNT_TYPE_DEBIT,
            currency='RUB',
            balance='50000.00',
        )
        Account.objects.filter(pk=account.pk).update(
            type_account=constants.ACCOUNT_TYPE_DEPOSIT,
        )
        account.refresh_from_db()
        deposit = Deposit.objects.create(
            account=account,
            name='Вклад',
            bank=_sberbank(),
        )
        term = DepositTerm.objects.create(
            deposit=deposit,
            opened_on=date(2025, 1, 1),
            matures_on=date(2026, 1, 1),
            payout_schedule_kind=DepositTerm.PayoutScheduleKind.CUSTOM,
            withdrawal_allowed=True,
            withdrawal_deadline=date(2025, 7, 1),
            minimum_balance=Decimal('10000.00'),
            top_up_allowed=True,
            top_up_deadline=date(2025, 8, 1),
        )
        term.rate_periods.create(
            starts_on=term.opened_on,
            ends_on=term.matures_on,
            annual_rate='12.50',
        )
        term.payout_schedule_dates.create(payout_on=date(2025, 6, 1))

        form = RenewDepositForm(term=term)

        self.assertEqual(form.initial['opened_on'], date(2026, 1, 2))
        self.assertEqual(form.initial['matures_on'], date(2027, 1, 2))
        self.assertEqual(form.initial['annual_rate'], Decimal('12.50'))
        self.assertEqual(
            form.initial['payout_schedule_kind'],
            DepositTerm.PayoutScheduleKind.CUSTOM,
        )
        self.assertEqual(form.initial['custom_payout_dates'], '02/06/2026')
        self.assertTrue(form.initial['withdrawal_allowed'])
        self.assertEqual(form.initial['withdrawal_deadline'], date(2026, 7, 2))
        self.assertEqual(form.initial['minimum_balance'], Decimal('10000.00'))
        self.assertEqual(form.initial['top_up_deadline'], date(2026, 8, 2))
        self.assertNotIn('name', form.fields)
        self.assertNotIn('balance', form.fields)


def _active_term(user: 'User') -> DepositTerm:
    service = ApplicationContainer().deposits.deposit_service()
    deposit = service.create_term_deposit(
        CreateDepositCommand(
            user=user,
            name='Вклад для формы подтверждения',
            bank=_sberbank(),
            currency='RUB',
            balance=Decimal('500.00'),
            opened_on=date(2026, 1, 1),
            matures_on=date(2026, 12, 31),
            annual_rate=Decimal('12.00'),
            rate_kind=DepositTerm.RateKind.FIXED,
        ),
    )
    return cast('DepositTerm', deposit.current_term)


class CapitalizeInterestFormTests(TestCase):
    def _base_data(self) -> dict[str, object]:
        return {
            'destination': 'capitalization',
            'gross': '100.00',
            'withholding': '10.00',
            'net': '90.00',
            'posting_on': '2026-07-01',
            'value_on': '2026-07-01',
        }

    def test_gross_label_states_amount_not_rate(self) -> None:
        user = cast('User', UserFactory())
        term = _active_term(user)

        form = CapitalizeInterestForm(term=term, user=user)

        self.assertEqual(
            str(form.fields['gross'].label),
            'Сумма начисленных процентов (в валюте вклада)',
        )

    def test_requires_reason_when_forecast_not_selected(self) -> None:
        """Hiding `forecast`/`reason` in the frontend scenario switch must
        not weaken server-side validation."""
        user = cast('User', UserFactory())
        term = _active_term(user)

        form = CapitalizeInterestForm(
            data=self._base_data(),
            term=term,
            user=user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn(
            'Выберите ожидаемую выплату или укажите причину',
            str(form.errors),
        )

    def test_reason_alone_is_sufficient_without_forecast(self) -> None:
        user = cast('User', UserFactory())
        term = _active_term(user)
        data = self._base_data()
        data['reason'] = 'Внеплановая выплата банка.'

        form = CapitalizeInterestForm(data=data, term=term, user=user)

        self.assertTrue(form.is_valid(), form.errors)

    def test_forecast_alone_is_sufficient_without_reason(self) -> None:
        user = cast('User', UserFactory())
        term = _active_term(user)
        forecast = term.interest_forecasts.create(
            payout_on=date(2026, 7, 1),
            amount=Decimal('90.00'),
            period_starts_on=date(2026, 1, 1),
            period_ends_on=date(2026, 7, 1),
        )
        data = self._base_data()
        data['forecast'] = forecast.pk

        form = CapitalizeInterestForm(data=data, term=term, user=user)

        self.assertTrue(form.is_valid(), form.errors)

    def test_internal_account_destination_requires_destination_account(
        self,
    ) -> None:
        user = cast('User', UserFactory())
        term = _active_term(user)
        data = self._base_data()
        data['reason'] = 'Внеплановая выплата банка.'
        data['destination'] = 'internal_account'

        form = CapitalizeInterestForm(data=data, term=term, user=user)

        self.assertFalse(form.is_valid())
        self.assertIn('destination_account', form.errors)


class CorrectPayoutScheduleFormTests(TestCase):
    def test_initial_values_come_from_the_term(self) -> None:
        user = cast('User', UserFactory())
        term = _active_term(user)
        term.payout_schedule_kind = DepositTerm.PayoutScheduleKind.MONTHLY
        term.interest_payout_destination = 'internal_account'
        term.save(
            update_fields=[
                'payout_schedule_kind',
                'interest_payout_destination',
            ],
        )

        form = CorrectPayoutScheduleForm(term=term)

        self.assertEqual(
            form.initial['payout_schedule_kind'],
            DepositTerm.PayoutScheduleKind.MONTHLY,
        )
        self.assertEqual(
            form.initial['interest_payout_destination'],
            'internal_account',
        )

    def test_offers_the_full_set_of_choices_including_custom_and_external(
        self,
    ) -> None:
        user = cast('User', UserFactory())
        term = _active_term(user)

        form = CorrectPayoutScheduleForm(term=term)
        schedule_field = cast(
            'ChoiceField',
            form.fields['payout_schedule_kind'],
        )
        destination_field = cast(
            'ChoiceField',
            form.fields['interest_payout_destination'],
        )
        schedule_choices = cast(
            'list[tuple[str, str]]',
            schedule_field.choices,
        )
        destination_choices = cast(
            'list[tuple[str, str]]',
            destination_field.choices,
        )

        schedule_values = [choice[0] for choice in schedule_choices]
        destination_values = [choice[0] for choice in destination_choices]
        self.assertIn(DepositTerm.PayoutScheduleKind.CUSTOM, schedule_values)
        self.assertIn('external', destination_values)
