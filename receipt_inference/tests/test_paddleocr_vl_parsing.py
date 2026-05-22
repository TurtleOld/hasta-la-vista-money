"""Tests for PaddleOCR-VL receipt parsing."""

from unittest import TestCase

from receipt_inference.config import load_settings
from receipt_inference.pipeline import PaddleOCRVLBackend


class PaddleOCRVLParsingTests(TestCase):
    def test_collect_payload_parts_accumulates_items_from_all_tables(
        self,
    ) -> None:
        backend = PaddleOCRVLBackend(load_settings())
        blocks = [
            {
                'block_label': 'table',
                'block_content': (
                    '<table><tr><td>ПРЕДМЕТ РАСЧЕТА</td><td>ЦЕНА, ₽</td>'
                    '<td>КОЛ-ВО</td><td>СУММА, ₽</td></tr>'
                    '<tr><td>1. Услуги сервиса Доставка</td>'
                    '<td>169,00</td><td>1</td><td>169,00</td></tr>'
                    '</table>'
                ),
            },
            {
                'block_label': 'table',
                'block_content': (
                    '<table><tr><td>ПРЕДМЕТ РАСЧЕТА</td><td>ЦЕНА, ₽</td>'
                    '<td>КОЛ-ВО</td><td>СУММА, ₽</td></tr>'
                    '<tr><td>2. Услуги сервиса Авито Доставка для продавца'
                    '</td><td>63,00</td><td>1</td><td>63,00</td></tr>'
                    '</table>'
                ),
            },
            {
                'block_label': 'table',
                'block_content': (
                    '<table><tr><td>ИТОГ:</td><td>232,00</td></tr></table>'
                ),
            },
        ]

        _title, _text, _metadata, payload = backend._collect_payload_parts(
            blocks,
        )

        self.assertEqual(payload['total_sum'], '232.00')
        self.assertEqual(
            [item['amount'] for item in payload['items']],
            ['169.00', '63.00'],
        )
        self.assertEqual(
            [item['product_name'] for item in payload['items']],
            [
                'Услуги сервиса Доставка',
                'Услуги сервиса Авито Доставка для продавца',
            ],
        )

    def test_collect_payload_parts_parses_quantity_amount_tables(self) -> None:
        backend = PaddleOCRVLBackend(load_settings())
        blocks = [
            {
                'block_label': 'table',
                'block_content': (
                    '<table><tr><td>ПРЕДМЕТ РАСЧЕТА</td><td>КОЛ-ВО</td>'
                    '<td>СУММА, ₽</td></tr>'
                    '<tr><td>1. Герметик Стиз А 0.44 кг.</td>'
                    '<td>1</td><td>309,64</td></tr>'
                    '<tr><td>2. Крышка универсальная</td>'
                    '<td>2</td><td>675,20</td></tr>'
                    '</table>'
                ),
            },
        ]

        _title, _text, _metadata, payload = backend._collect_payload_parts(
            blocks,
        )

        self.assertEqual(
            [item['amount'] for item in payload['items']],
            ['309.64', '675.20'],
        )
        self.assertEqual(
            [item['price'] for item in payload['items']],
            ['309.64', '337.60'],
        )
