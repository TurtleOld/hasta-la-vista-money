"""Sberbank traceability: every potential operation becomes a row."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pandas as pd
from django.test import SimpleTestCase

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import Transaction
from hasta_la_vista_money.users.models import BankStatementRow
from hasta_la_vista_money.users.services.bank_statement import (
    _SberbankParser,
)
from hasta_la_vista_money.users.tests.statement_identity_fixtures import (
    statement_identity_settings,
)
from hasta_la_vista_money.users.tests.statement_traceability_fixtures import (
    StatementTraceabilityTestCase,
    pdf_path,
    row,
)


class SberbankParserTraceabilityTest(SimpleTestCase):
    def test_row_without_amount_keeps_known_fields(self) -> None:
        path = pdf_path()
        self.addCleanup(path.unlink)
        parser = _SberbankParser(path)
        df = pd.DataFrame(
            [
                ['18.02.2026 17:11', 'Транспорт', '', '1 000,00 ₽'],
                ['18.02.2026 / 123', 'Описание', '', ''],
            ],
        )
        transactions = parser._parse_table(df)

        self.assertEqual(len(transactions), 1)
        transaction = transactions[0]
        self.assertEqual(transaction['parse_error_code'], 'missing_amount')
        self.assertIsNone(transaction['amount'])
        self.assertEqual(transaction['description'], 'Транспорт')
        self.assertEqual(transaction['source_ref'], '123')


@statement_identity_settings
class SberbankImportTraceabilityTest(StatementTraceabilityTestCase):
    bank_code = constants.BANK_CODE_SBERBANK

    def test_posted_operation_has_a_row(self) -> None:
        upload, result = self.import_rows(
            [
                row(
                    amount='-100.00',
                    description='Транспорт',
                    source_ref='sber-1',
                    category_name='Транспорт',
                ),
            ],
        )

        self.assertEqual(result['expense_count'], 1)
        statement_row = self.rows(upload).get()
        self.assertEqual(statement_row.decision, BankStatementRow.Decision.NEW)
        self.assertIsNotNone(statement_row.transaction_id)
        self.assertEqual(upload.processing_traceability_version, 1)
        self.assertIsNotNone(upload.processing_verified_at)

    def test_exact_duplicate_has_a_linked_row_and_no_movement(self) -> None:
        first = self.upload('first.pdf', file_hash='first')
        self.import_rows(
            [
                row(
                    amount='-100.00',
                    source_ref='sber-dup',
                    category_name='Транспорт',
                ),
            ],
            upload=first,
        )
        movement = Transaction.objects.get()

        second = self.upload('second.pdf', file_hash='second')
        _, result = self.import_rows(
            [
                row(
                    amount='-100.00',
                    source_ref='sber-dup',
                    category_name='Транспорт',
                ),
            ],
            upload=second,
        )

        self.assertEqual(result['expense_count'], 0)
        self.assertEqual(result['skipped_count'], 1)
        duplicate = self.rows(second).get()
        self.assertEqual(duplicate.decision, BankStatementRow.Decision.LINKED)
        self.assertEqual(duplicate.transaction_id, movement.pk)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_credit_repayment_duplicate_is_not_a_second_repayment(self) -> None:
        card = Account.objects.create(
            user=self.user,
            name_account='Кредитка',
            type_account=constants.ACCOUNT_TYPE_CREDIT_CARD,
            balance=Decimal('0.00'),
            limit_credit=Decimal('100000.00'),
            currency='RUB',
        )
        first = self.upload('first.pdf', file_hash='first', account=card)
        self.import_rows(
            [row(amount='100.00', source_ref='repay-1')],
            upload=first,
        )
        self.assertEqual(
            self.rows(first).get().decision,
            BankStatementRow.Decision.NEEDS_TRANSFER,
        )

        second = self.upload('second.pdf', file_hash='second', account=card)
        _, result = self.import_rows(
            [row(amount='100.00', source_ref='repay-1')],
            upload=second,
        )

        self.assertEqual(result['needs_transfer_count'], 0)
        duplicate = self.rows(second).get()
        self.assertEqual(duplicate.decision, BankStatementRow.Decision.PENDING)
        self.assertEqual(
            duplicate.duplicate_of_id,
            self.rows(first).get().pk,
        )
        self.assertEqual(
            self.rows(second)
            .filter(decision=BankStatementRow.Decision.NEEDS_TRANSFER)
            .count(),
            0,
        )

    def test_unknown_category_waits_for_markup_without_network(self) -> None:
        with patch(
            'core.services.external_model.httpx.Client',
        ) as mock_client:
            upload, result = self.import_rows(
                [row(amount='-100.00', description='Неизвестный магазин')],
            )

        mock_client.assert_not_called()
        self.assertEqual(result['expense_count'], 0)
        self.assertFalse(Transaction.objects.exists())
        statement_row = self.rows(upload).get()
        self.assertEqual(
            statement_row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )

    def test_parse_error_row_is_kept_and_blocks_completion(self) -> None:
        upload, result = self.import_rows(
            [
                row(
                    amount=None,
                    description='Транспорт',
                    source_ref='bad-1',
                    parse_error_code='missing_amount',
                ),
            ],
        )

        self.assertEqual(result['expense_count'], 0)
        self.assertFalse(Transaction.objects.exists())
        statement_row = self.rows(upload).get()
        self.assertEqual(
            statement_row.decision,
            BankStatementRow.Decision.PARSE_ERROR,
        )
        self.assertEqual(upload.status, 'awaiting_confirmation')
        self.assertEqual(upload.awaiting_decision_count, 1)

    def test_empty_document_proves_traceability(self) -> None:
        upload, _ = self.import_rows([])

        self.assertFalse(self.rows(upload).exists())
        self.assertEqual(upload.processing_traceability_version, 1)

    def test_legacy_parser_result_does_not_claim_traceability(self) -> None:
        upload, _ = self.import_rows(
            [row(amount='-10.00', source_ref='sber-x')],
            traceability_complete=False,
        )

        self.assertEqual(upload.processing_traceability_version, 0)
        self.assertIsNone(upload.processing_verified_at)
