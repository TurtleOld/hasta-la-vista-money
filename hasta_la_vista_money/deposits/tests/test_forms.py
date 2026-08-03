from datetime import date
from typing import TYPE_CHECKING, cast

from django.forms import ChoiceField, DateField, DateInput, ModelChoiceField
from django.test import TestCase

from hasta_la_vista_money import constants
from hasta_la_vista_money.deposits.forms import (
    AddFloatingRatePeriodForm,
    CreateDepositForm,
)
from hasta_la_vista_money.deposits.models import DepositTerm
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
