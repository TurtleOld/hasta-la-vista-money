from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.test import SimpleTestCase

from hasta_la_vista_money.users.services.bank_statement import (
    RosDorBankRowKind,
    _create_parser,
    _RosDorBankParser,
    rosdorbank_merchant_key,
)

FIXTURE = Path(__file__).parent / 'fixtures' / 'rosdorbank_statement.pdf'


class RosDorBankMerchantKeyTest(SimpleTestCase):
    def test_spec_examples(self) -> None:
        cases = {
            'PMP STRELKACARD13.': 'STRELKACARD',
            'PMP STRELKACARD1_1': 'STRELKACARD',
            '3DI2 NALOG. RU': 'NALOGRU',
            'PMP CPPK- 2000753- BPA20': 'CPPK',
            'PMP CH50103': 'CH50103',
            'АПТЕКА 77-278_SBP': 'АПТЕКА',
        }
        for text, key in cases.items():
            with self.subTest(text=text):
                self.assertEqual(rosdorbank_merchant_key(text), key)


class RosDorBankParserTest(SimpleTestCase):
    def test_detects_rosdorbank_statement(self) -> None:
        self.assertIsInstance(_create_parser(FIXTURE), _RosDorBankParser)

    def test_parses_header_and_closing_balance(self) -> None:
        result = _RosDorBankParser(FIXTURE).parse()

        self.assertEqual(result.account_number, '40817810000000000001')
        self.assertEqual(result.period_start, date(2026, 3, 1))
        self.assertEqual(result.closing_balance_date, date(2026, 3, 3))
        self.assertEqual(result.closing_balance, Decimal('56000.00'))

    def test_parses_every_row_kind(self) -> None:
        result = _RosDorBankParser(FIXTURE).parse()

        def row(t: dict[str, Any]) -> tuple[Any, ...]:
            return (
                t['source_ref'],
                t['date'].date(),
                t['amount'],
                t['kind'],
                t['description'],
                t['merchant_key'],
                t['counterparty_account'],
            )

        card_acc = '30232810000000000001'
        own_acc = '40817810000000000002'
        mar1, mar2, mar3 = date(2026, 3, 1), date(2026, 3, 2), date(2026, 3, 3)
        kind = RosDorBankRowKind
        self.assertEqual(
            [row(t) for t in result.transactions],
            [
                (
                    '101-01.03.2026',
                    mar1,
                    Decimal('-350.00'),
                    kind.CARD,
                    'PMP STRELKACARD13.',
                    'STRELKACARD',
                    card_acc,
                ),
                (
                    '102-01.03.2026',
                    mar1,
                    Decimal('-120.00'),
                    kind.CARD,
                    '3DI2 NALOG. RU',
                    'NALOGRU',
                    card_acc,
                ),
                (
                    '103-01.03.2026',
                    mar1,
                    Decimal('120.00'),
                    kind.CANCEL,
                    '3DI2 NALOG. RU',
                    'NALOGRU',
                    card_acc,
                ),
                (
                    '104-01.03.2026',
                    mar1,
                    Decimal('-1000.00'),
                    kind.OWN_C2C,
                    'Тест Тестович Т',
                    None,
                    own_acc,
                ),
                (
                    '105-01.03.2026',
                    mar1,
                    Decimal('-500.00'),
                    kind.C2C,
                    'Пример Примерович П',
                    None,
                    '40817810000000000003',
                ),
                (
                    '106-02.03.2026',
                    mar2,
                    Decimal('-2345.67'),
                    kind.C2B,
                    'АПТЕКА 77-278_SBP — Заказ',
                    'АПТЕКА',
                    '30232810000000000004',
                ),
                (
                    '107-02.03.2026',
                    mar2,
                    Decimal('10000.00'),
                    kind.UNKNOWN,
                    'КВыдачеБанк (по документу - )',
                    None,
                    '60305810000000000006',
                ),
                (
                    '108-02.03.2026',
                    mar2,
                    Decimal('-80.00'),
                    kind.UNKNOWN,
                    'Перевод по номеру телефона',
                    None,
                    '40817810000000000007',
                ),
                (
                    '109-02.03.2026',
                    mar2,
                    Decimal('700.00'),
                    kind.OWN_C2C,
                    'Тестов Тест Тестович',
                    None,
                    own_acc,
                ),
                (
                    '110-03.03.2026',
                    mar3,
                    Decimal('-424.33'),
                    kind.CARD,
                    'PMP CH50103',
                    'CH50103',
                    card_acc,
                ),
            ],
        )
        self.assertTrue(
            all(t['source'] == 'rosdorbank' for t in result.transactions),
        )

    def test_incoming_c2c_without_name_gets_fallback_description(
        self,
    ) -> None:
        kind, description, _ = _RosDorBankParser(FIXTURE)._classify(
            'ИНН: 0 ',
            'СБП- c2C. ID A1, тел C: +79000000001, тел c: +79000000002',
        )

        self.assertEqual(kind, RosDorBankRowKind.C2C)
        self.assertEqual(description, 'Перевод СБП')

    def test_descriptions_have_no_phones_addresses_or_inn(self) -> None:
        result = _RosDorBankParser(FIXTURE).parse()

        for t in result.transactions:
            with self.subTest(source_ref=t['source_ref']):
                for marker in ('+7', '900', 'ИНН', 'РОССИЯ', 'ВЫДУМАННАЯ'):
                    self.assertNotIn(marker, t['description'])
