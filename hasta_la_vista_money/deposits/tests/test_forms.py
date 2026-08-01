from typing import TYPE_CHECKING, cast

from django.forms import DateField, DateInput, ModelChoiceField
from django.test import TestCase

from hasta_la_vista_money import constants
from hasta_la_vista_money.deposits.forms import CreateDepositForm
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.factories import UserFactory

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User


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
                'bank': 'SBERBANK',
                'currency': 'RUB',
                'balance': '50000.00',
                'opened_on': '2026-08-01',
                'matures_on': '2027-02-01',
                'annual_rate': '15.50',
                'opening_method': 'funding',
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
                'bank': 'SBERBANK',
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
