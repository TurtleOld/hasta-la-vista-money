from django.forms import DateField, DateInput
from django.test import SimpleTestCase

from hasta_la_vista_money import constants
from hasta_la_vista_money.deposits.forms import CreateDepositForm


class CreateDepositFormTests(SimpleTestCase):
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
