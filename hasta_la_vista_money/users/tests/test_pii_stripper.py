from django.test import TestCase

from hasta_la_vista_money.users.services.pii_stripper import strip_pii


class TestStripPii(TestCase):
    def test_removes_masked_card(self):
        self.assertEqual(strip_pii('Оплата *4321 MAGNIT'), 'Оплата MAGNIT')

    def test_removes_auth_code(self):
        self.assertEqual(strip_pii('NETFLIX.COM 123456'), 'NETFLIX.COM')

    def test_removes_date_fragment(self):
        self.assertEqual(strip_pii('SPAR 12.03.2025 Москва'), 'SPAR Москва')

    def test_preserves_clean_description(self):
        self.assertEqual(strip_pii('Продукты питания'), 'Продукты питания')

    def test_collapses_extra_spaces(self):
        self.assertEqual(strip_pii('Яндекс  Такси  *1234'), 'Яндекс Такси')

    def test_empty_string(self):
        self.assertEqual(strip_pii(''), '')
