"""Raiffeisen traceability: explicit columns, local categories, no drops."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
from django.test import SimpleTestCase

from hasta_la_vista_money import constants
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import BankStatementRow
from hasta_la_vista_money.users.services.bank_statement import (
    _RaiffeisenBankParser,
)
from hasta_la_vista_money.users.tests.statement_identity_fixtures import (
    statement_identity_settings,
)
from hasta_la_vista_money.users.tests.statement_traceability_fixtures import (
    StatementTraceabilityTestCase,
    pdf_path,
    row,
)


class RaiffeisenParserTraceabilityTest(SimpleTestCase):
    def _parser(self) -> _RaiffeisenBankParser:
        path = pdf_path()
        self.addCleanup(path.unlink)
        return _RaiffeisenBankParser(path)

    def test_potential_row_without_amount_stays_a_problem(self) -> None:
        parser = self._parser()
        df = pd.DataFrame(
            [
                ['1', '28.12.2025 11:10', 'ZP0000001', '', '', 'Описание', ''],
            ],
        )

        transactions = parser._parse_table(df)

        self.assertEqual(len(transactions), 1)
        self.assertEqual(
            transactions[0]['parse_error_code'],
            'missing_amount',
        )
        self.assertIsNone(transactions[0]['amount'])
        self.assertEqual(transactions[0]['source_ref'], '0000001')

    def test_income_and_expense_columns_define_direction(self) -> None:
        parser = self._parser()
        df = pd.DataFrame(
            [
                [
                    '1',
                    '28.12.2025 11:10',
                    'ZP0000001',
                    '+ 1 500,00 ₽',
                    '',
                    'ЗП',
                    '',
                ],
                ['2', '28.12.2025 11:11', 'ZP2', '', '- 13,20 ₽', 'Кофе', ''],
            ],
        )

        transactions = parser._parse_table(df)

        self.assertEqual(
            [item['transaction_type'] for item in transactions],
            ['income', 'expense'],
        )
        self.assertEqual(
            [item['amount'] for item in transactions],
            [Decimal('1500.00'), Decimal('-13.20')],
        )


@statement_identity_settings
class RaiffeisenImportTraceabilityTest(StatementTraceabilityTestCase):
    bank_code = constants.BANK_CODE_RAIFFEISEN

    def test_local_category_posts_a_traceable_row(self) -> None:
        Category.objects.create(
            user=self.user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        upload, result = self.import_rows(
            [
                row(
                    amount='-250.00',
                    description='Оплата Продукты',
                    source_ref='raif-1',
                ),
            ],
        )

        self.assertEqual(result['expense_count'], 1)
        statement_row = self.rows(upload).get()
        self.assertEqual(statement_row.decision, BankStatementRow.Decision.NEW)
        if statement_row.transaction is None:
            self.fail('Posted row has no movement')
        self.assertEqual(
            statement_row.transaction.category.name,
            'Продукты',
        )

    def test_unknown_local_category_waits_for_markup(self) -> None:
        upload, result = self.import_rows(
            [
                row(
                    amount='-250.00',
                    description='Неизвестный магазин',
                    source_ref='raif-2',
                ),
            ],
        )

        self.assertEqual(result['expense_count'], 0)
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(
            self.rows(upload).get().decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )

    def test_exact_duplicate_keeps_a_linked_representation(self) -> None:
        Category.objects.create(
            user=self.user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        first = self.upload('first.pdf', file_hash='first')
        self.import_rows(
            [
                row(
                    amount='-250.00',
                    description='Оплата Продукты',
                    source_ref='raif-dup',
                ),
            ],
            upload=first,
        )
        movement = Transaction.objects.get()

        second = self.upload('second.pdf', file_hash='second')
        _, result = self.import_rows(
            [
                row(
                    amount='-250.00',
                    description='Оплата Продукты',
                    source_ref='raif-dup',
                ),
            ],
            upload=second,
        )

        self.assertEqual(result['skipped_count'], 1)
        duplicate = self.rows(second).get()
        self.assertEqual(duplicate.decision, BankStatementRow.Decision.LINKED)
        self.assertEqual(duplicate.transaction_id, movement.pk)
