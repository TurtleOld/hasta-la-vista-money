"""Shared synthetic statements for per-bank traceability tests.

No real PDFs and no real financial data: parser tables and results are built
in memory.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

from django.test import TestCase

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.services.bank_statement import (
    StatementParseResult,
)
from hasta_la_vista_money.users.tasks import (
    process_bank_statement_typed as process_bank_statement_task,
)

if TYPE_CHECKING:
    from django.db.models import QuerySet

WHEN = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
PARSER_PATH = (
    'hasta_la_vista_money.users.services.bank_statement_import.'
    'BankStatementParser'
)


def row(
    *,
    amount: str | None,
    description: str = 'Операция',
    source_ref: str | None = None,
    position: int = 0,
    category_name: str | None = None,
    parse_error_code: str = '',
    source: str = '',
    when: datetime | None = WHEN,
) -> dict[str, Any]:
    """Build one traceable parser result row."""
    return {
        'row_position': position,
        'date': when,
        'amount': None if amount is None else Decimal(amount),
        'description': description,
        'source_ref': source_ref,
        'category_name': category_name,
        'parse_error_code': parse_error_code,
        'source': source,
    }


def pdf_path() -> Path:
    """Create a placeholder PDF path like the other synthetic tests."""
    with NamedTemporaryFile(mode='wb', suffix='.pdf', delete=False) as handle:
        handle.write(b'%PDF-1.4 synthetic pdf')
        return Path(handle.name)


class StatementTraceabilityTestCase(TestCase):
    """Accounts, uploads, and a scripted parser for one bank."""

    fixtures: list[str] = ['users.yaml']

    bank_code = ''
    account_type = ''

    def setUp(self) -> None:
        self.user: User = User.objects.get(pk=1)
        account_fields: dict[str, Any] = {
            'user': self.user,
            'name_account': 'Счёт',
            'balance': Decimal('1000.00'),
            'currency': 'RUB',
        }
        if self.account_type:
            account_fields['type_account'] = self.account_type
        self.account = Account.objects.create(**account_fields)

    def upload(
        self,
        name: str = 'statement.pdf',
        *,
        file_hash: str = '',
        account: Account | None = None,
    ) -> BankStatementUpload:
        return BankStatementUpload.objects.create(
            user=self.user,
            account=account or self.account,
            pdf_file=name,
            file_hash=file_hash or name,
            status=BankStatementUpload.Status.PENDING,
        )

    def import_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        upload: BankStatementUpload | None = None,
        traceability_complete: bool = True,
        period_start: date | None = None,
        period_end: date | None = None,
    ) -> tuple[BankStatementUpload, dict[str, Any]]:
        upload = upload or self.upload()
        parser = MagicMock()
        parser.parse.return_value = StatementParseResult(
            transactions=rows,
            bank_code=self.bank_code,
            traceability_complete=traceability_complete,
            period_start=period_start,
            period_end=period_end,
        )
        with patch(PARSER_PATH, return_value=parser):
            result: dict[str, Any] = process_bank_statement_task.apply(
                args=[upload.pk],
            ).get()
        upload.refresh_from_db()
        return upload, result

    def rows(
        self,
        upload: BankStatementUpload,
    ) -> QuerySet[BankStatementRow]:
        return BankStatementRow.objects.filter(upload=upload)
