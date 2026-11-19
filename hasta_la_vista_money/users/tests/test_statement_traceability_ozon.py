"""Ozon traceability: unsupported operations stay visible as problems."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
from django.test import SimpleTestCase

from hasta_la_vista_money import constants
from hasta_la_vista_money.transactions.models import Transaction
from hasta_la_vista_money.users.models import BankStatementRow
from hasta_la_vista_money.users.services.bank_statement import (
    _OzonBankParser,
)
from hasta_la_vista_money.users.tests.statement_identity_fixtures import (
    statement_identity_settings,
)
from hasta_la_vista_money.users.tests.statement_traceability_fixtures import (
    StatementTraceabilityTestCase,
    pdf_path,
    row,
)


class OzonParserTraceabilityTest(SimpleTestCase):
    def _parse(self, table: list[list[str]]) -> list[dict[str, Any]]:
        path = pdf_path()
        self.addCleanup(path.unlink)
        parser = _OzonBankParser(path)
        with patch(
            'hasta_la_vista_money.users.services.bank_statement.camelot',
        ) as mock_camelot:
            mock_table = MagicMock()
            mock_table.df = pd.DataFrame(table)
            mock_table.page = '1'
            mock_camelot.read_pdf.return_value = [mock_table]
            return parser.parse().transactions

    def test_unsupported_operation_keeps_known_fields(self) -> None:
        transactions = self._parse(
            [
                [
                    '05.08.2026 10:00:00',
                    'doc-1',
                    'Перевод через СБП',
                    '+ 500.00 ₽',
                ],
            ],
        )

        self.assertEqual(len(transactions), 1)
        item = transactions[0]
        self.assertEqual(item['parse_error_code'], 'missing_operation')
        self.assertEqual(item['amount'], Decimal('500.00'))
        self.assertEqual(item['source_ref'], 'doc-1')
        self.assertEqual(item['transaction_type'], 'income')

    def test_empty_document_is_a_valid_empty_parse(self) -> None:
        transactions = self._parse([['', '', '', '']])

        self.assertEqual(transactions, [])


@statement_identity_settings
class OzonImportTraceabilityTest(StatementTraceabilityTestCase):
    bank_code = constants.BANK_CODE_OZON

    def test_explicit_local_category_posts_a_row_without_classifier(
        self,
    ) -> None:
        with patch(
            'hasta_la_vista_money.users.services.category_classifier.'
            'LocalCategoryClassifier.classify',
        ) as classify:
            upload, result = self.import_rows(
                [
                    row(
                        amount='-500.00',
                        description='Покупки Ozon',
                        category_name='Покупки Ozon',
                        source_ref='ozon-1',
                        source='ozon',
                    ),
                ],
            )

        classify.assert_not_called()
        self.assertEqual(result['expense_count'], 1)
        statement_row = self.rows(upload).get()
        self.assertEqual(statement_row.decision, BankStatementRow.Decision.NEW)
        self.assertEqual(statement_row.suggested_category, 'Покупки Ozon')

    def test_unsupported_operation_is_kept_as_a_problem(self) -> None:
        upload, result = self.import_rows(
            [
                row(
                    amount='+500.00',
                    description='Перевод через СБП',
                    parse_error_code='missing_operation',
                    source_ref='ozon-transfer',
                    source='ozon',
                ),
            ],
        )

        self.assertEqual(result['income_count'], 0)
        self.assertFalse(Transaction.objects.exists())
        statement_row = self.rows(upload).get()
        self.assertEqual(
            statement_row.decision,
            BankStatementRow.Decision.PARSE_ERROR,
        )
        self.assertEqual(upload.status, 'awaiting_confirmation')

    def test_exact_duplicate_has_a_linked_row(self) -> None:
        first = self.upload('first.pdf', file_hash='first')
        self.import_rows(
            [
                row(
                    amount='-500.00',
                    description='Покупки Ozon',
                    category_name='Покупки Ozon',
                    source_ref='ozon-dup',
                    source='ozon',
                ),
            ],
            upload=first,
        )
        movement = Transaction.objects.get()

        second = self.upload('second.pdf', file_hash='second')
        _, result = self.import_rows(
            [
                row(
                    amount='-500.00',
                    description='Покупки Ozon',
                    category_name='Покупки Ozon',
                    source_ref='ozon-dup',
                    source='ozon',
                ),
            ],
            upload=second,
        )

        self.assertEqual(result['skipped_count'], 1)
        duplicate = self.rows(second).get()
        self.assertEqual(duplicate.decision, BankStatementRow.Decision.LINKED)
        self.assertEqual(duplicate.transaction_id, movement.pk)
