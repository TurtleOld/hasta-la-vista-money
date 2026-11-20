"""Generic bank traceability: no guessed direction, no lost partial rows."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd
from django.test import SimpleTestCase

from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import BankStatementRow
from hasta_la_vista_money.users.services.bank_statement import (
    _GenericBankParser,
)
from hasta_la_vista_money.users.tests.statement_identity_fixtures import (
    statement_identity_settings,
)
from hasta_la_vista_money.users.tests.statement_traceability_fixtures import (
    StatementTraceabilityTestCase,
    pdf_path,
    row,
)


class GenericParserTraceabilityTest(SimpleTestCase):
    def _parser(self) -> _GenericBankParser:
        path = pdf_path()
        self.addCleanup(path.unlink)
        return _GenericBankParser(path)

    def test_unsigned_amount_does_not_guess_direction(self) -> None:
        parser = self._parser()
        df = pd.DataFrame(
            {
                0: ['01.01.2026 10:00', '1'],
                1: ['', ''],
                2: ['', 'Неизвестный магазин'],
                3: ['', ''],
                4: ['', ''],
                5: ['', '1500,00 ₽'],
                6: ['', ''],
            },
        )

        transactions = parser._parse_table(df)

        self.assertEqual(len(transactions), 1)
        self.assertEqual(
            transactions[0]['parse_error_code'],
            'missing_direction',
        )
        self.assertIsNone(transactions[0]['transaction_type'])

    def test_partial_row_does_not_remove_valid_neighbours(self) -> None:
        parser = self._parser()
        df = pd.DataFrame(
            {
                0: ['01.01.2026 10:00', '1', '2'],
                1: ['', '', ''],
                2: ['', 'Магазин', 'Кафе'],
                3: ['', '', ''],
                4: ['', '', ''],
                5: ['', '1500,00 ₽', '-200,00 ₽'],
                6: ['', '', ''],
            },
        )

        transactions = parser._parse_table(df)

        self.assertEqual(len(transactions), 2)
        self.assertEqual(
            transactions[0]['parse_error_code'],
            'missing_direction',
        )
        self.assertEqual(transactions[1]['parse_error_code'], '')
        self.assertEqual(transactions[1]['amount'], Decimal('-200.00'))
        self.assertEqual(
            [item['row_position'] for item in transactions],
            [0, 1],
        )


@statement_identity_settings
class GenericImportTraceabilityTest(StatementTraceabilityTestCase):
    bank_code = ''

    def test_unknown_category_waits_for_markup(self) -> None:
        upload, result = self.import_rows(
            [row(amount='-200.00', description='Неизвестный магазин')],
        )

        self.assertEqual(result['expense_count'], 0)
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(
            self.rows(upload).get().decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )

    def test_local_category_posts_a_traceable_row(self) -> None:
        Category.objects.create(
            user=self.user,
            name='Кафе',
            type=TransactionType.EXPENSE,
        )
        upload, result = self.import_rows(
            [row(amount='-200.00', description='Оплата Кафе')],
        )

        self.assertEqual(result['expense_count'], 1)
        statement_row = self.rows(upload).get()
        self.assertEqual(statement_row.decision, BankStatementRow.Decision.NEW)
        if statement_row.transaction is None:
            self.fail('Posted row has no movement')
        self.assertEqual(statement_row.transaction.category.name, 'Кафе')

    def test_parse_error_keeps_a_row_and_no_money(self) -> None:
        upload, _ = self.import_rows(
            [
                row(
                    amount=None,
                    description='Магазин',
                    parse_error_code='missing_amount',
                ),
            ],
        )

        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(
            self.rows(upload).get().decision,
            BankStatementRow.Decision.PARSE_ERROR,
        )

    def test_traceability_version_requires_a_complete_parser(self) -> None:
        complete, _ = self.import_rows(
            [],
            upload=self.upload('complete.pdf'),
            traceability_complete=True,
        )
        incomplete, _ = self.import_rows(
            [],
            upload=self.upload('incomplete.pdf'),
            traceability_complete=False,
        )

        self.assertEqual(complete.processing_traceability_version, 1)
        self.assertEqual(incomplete.processing_traceability_version, 0)

    def test_documented_period_is_persisted_on_empty_document(self) -> None:
        upload, _ = self.import_rows(
            [],
            period_start=date(2026, 2, 1),
            period_end=date(2026, 2, 28),
        )

        self.assertEqual(upload.statement_period_start, date(2026, 2, 1))
        self.assertEqual(upload.statement_period_end, date(2026, 2, 28))
        self.assertEqual(upload.processing_traceability_version, 1)

    def test_operation_dates_do_not_invent_period_bounds(self) -> None:
        upload, _ = self.import_rows(
            [
                row(
                    amount='-10.00',
                    when=datetime(2026, 2, 10, 12, tzinfo=UTC),
                ),
            ],
        )

        self.assertIsNone(upload.statement_period_start)
        self.assertIsNone(upload.statement_period_end)

    def test_unknown_period_keeps_documented_bounds(self) -> None:
        first = self.upload('period.pdf')
        self.import_rows(
            [],
            upload=first,
            period_start=date(2026, 2, 1),
            period_end=date(2026, 2, 28),
        )

        upload, _ = self.import_rows([], upload=first)

        self.assertEqual(upload.statement_period_start, date(2026, 2, 1))
        self.assertEqual(upload.statement_period_end, date(2026, 2, 28))
