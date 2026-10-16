from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import reverse

from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.users.services.export import escape_csv_cell


class EscapeCsvCellTest(TestCase):
    def test_formula_prefixes_are_escaped(self) -> None:
        for prefix in ('=', '+', '-', '@', '\t', '\r'):
            with self.subTest(prefix=prefix):
                self.assertEqual(
                    escape_csv_cell(f'{prefix}SUM(A1)'),
                    f"'{prefix}SUM(A1)",
                )

    def test_plain_and_non_string_values_are_kept(self) -> None:
        self.assertEqual(escape_csv_cell('Кафе'), 'Кафе')
        self.assertEqual(escape_csv_cell(''), '')
        self.assertEqual(escape_csv_cell(Decimal('-5.00')), Decimal('-5.00'))


class StatisticsExportCsvInjectionTest(TestCase):
    def test_export_escapes_user_controlled_cells(self) -> None:
        user = User.objects.create_user(username='csv-user', password='x')
        self.client.force_login(user)
        paginator = MagicMock()
        paginator.paginator.object_list = []
        stats = {
            'months_data': [],
            'income_expense': [
                {
                    'date': '2026-01-01',
                    'type': 'expense',
                    'category__name': '=HYPERLINK("http://evil")',
                    'account__name_account': 'acc',
                    'user__username': 'u',
                    'amount': Decimal('1.00'),
                },
            ],
            'receipt_page': paginator,
            'payment_calendar': [],
        }
        with patch(
            'hasta_la_vista_money.users.views.profile'
            '.get_user_detailed_statistics',
            return_value=stats,
        ):
            response = self.client.get(reverse('users:statistics_export'))

        content = response.content.decode()
        self.assertIn("'=HYPERLINK", content)
        self.assertNotIn(',=HYPERLINK', content)
