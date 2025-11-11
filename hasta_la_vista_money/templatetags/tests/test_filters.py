from django.test import SimpleTestCase

from hasta_la_vista_money.templatetags.dict_get import dict_get
from hasta_la_vista_money.templatetags.thousand_comma import comma


class TemplateFiltersTest(SimpleTestCase):
    def test_dict_get_returns_value(self) -> None:
        data = {'key': 'value'}
        self.assertEqual(dict_get(data, 'key'), 'value')

    def test_dict_get_returns_none_for_missing_key(self) -> None:
        self.assertIsNone(dict_get({}, 'missing'))

    def test_comma_formats_numbers(self) -> None:
        self.assertEqual(comma(1234.5), '1 234.50')

    def test_comma_handles_none(self) -> None:
        self.assertEqual(comma(None), '—')
        self.assertEqual(comma(''), '—')

    def test_comma_handles_invalid_value(self) -> None:
        self.assertEqual(comma(object()), '—')

