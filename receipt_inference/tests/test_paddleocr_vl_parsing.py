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

    def test_build_payload_adds_numbered_text_items_missing_from_tables(
        self,
    ) -> None:
        backend = PaddleOCRVLBackend(load_settings())
        blocks = [
            {
                'block_label': 'text',
                'block_content': (
                    '1. Мука пшеничная\n'
                    'категории 1,7-2 кг, Финляндия\n'
                    '478,00 1 478,00'
                ),
            },
            {
                'block_label': 'table',
                'block_content': (
                    '<table><tr><td>2. Пакет-майка OZON</td>'
                    '<td>8,48</td><td>1</td><td>8,48</td></tr>'
                    '<tr><td>FRESH 35+18x61</td><td></td><td></td>'
                    '<td></td></tr></table>'
                ),
            },
            {
                'block_label': 'table',
                'block_content': (
                    '<table><tr><td>ИТОГ:</td><td>486,48</td></tr></table>'
                ),
            },
        ]

        payload = backend._build_payload_from_blocks(blocks)

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload['total_sum'], '486.48')
        self.assertEqual(
            [item['amount'] for item in payload['items']],
            ['478.00', '8.48'],
        )
        self.assertEqual(payload['items'][0]['quantity'], '1')

    def test_build_payload_adds_placeholder_for_fully_missing_item(
        self,
    ) -> None:
        backend = PaddleOCRVLBackend(load_settings())
        blocks = [
            {
                'block_label': 'table',
                'block_content': (
                    '<table><tr><td>2. Пакет-майка OZON</td>'
                    '<td>8,48</td><td>1</td><td>8,48</td></tr>'
                    '<tr><td>3. Макароны Makfa</td><td>56,79</td>'
                    '<td>1</td><td>56,79</td></tr>'
                    '<tr><td>4. Молоко</td><td>63,19</td>'
                    '<td>2</td><td>126,38</td></tr>'
                    '<tr><td>5. Квас 2 л, Ozon fresh</td>'
                    '<td>197,93</td><td>1</td><td>197,93</td></tr>'
                    '<tr><td>6. Ветчина</td><td>200,45</td>'
                    '<td>1</td><td>200,45</td></tr>'
                    '<tr><td>7. Доставка</td><td>129,97</td>'
                    '<td>1</td><td>129,97</td></tr></table>'
                ),
            },
            {
                'block_label': 'table',
                'block_content': (
                    '<table><tr><td>ИТОГ:</td><td>1 198,00</td></tr></table>'
                ),
            },
        ]

        payload = backend._build_payload_from_blocks(blocks)

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(
            payload['items'][-1]['product_name'],
            'Нераспознанная позиция',
        )
        self.assertEqual(payload['items'][-1]['amount'], '478.00')
