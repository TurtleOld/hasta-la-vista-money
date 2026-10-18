"""The category classifier runs outside the per-row database transaction."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, ClassVar

from django.db import connection
from django.test import TestCase

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import BankStatementUpload, User


class _RecordingClassifier:
    def __init__(self) -> None:
        self.atomic_depths: list[int] = []

    def classify(
        self,
        description: str,
        transaction_type: str,
        existing_categories: list[str],
    ) -> str:
        del description, transaction_type, existing_categories
        self.atomic_depths.append(len(connection.atomic_blocks))
        return 'Разное'


class BankStatementImportClassifierTests(TestCase):
    fixtures: ClassVar[list[str]] = ['users.yaml']  # type: ignore[misc]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.create(
            user=self.user,
            name_account='Счёт',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='statement.pdf',
            file_hash='hash-1',
        )
        self.classifier = _RecordingClassifier()
        ApplicationContainer.users.category_classifier.override(
            self.classifier,
        )
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )
        self.service = (
            ApplicationContainer().users.bank_statement_import_service()
        )
        self.duplicate_date = datetime(2024, 1, 2, 12, tzinfo=UTC)
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=Category.objects.create(
                user=self.user,
                name='Продукты',
                type=TransactionType.EXPENSE,
            ),
            type=TransactionType.EXPENSE,
            amount=Decimal('200.00'),
            date=self.duplicate_date,
        )

    def _rows(self) -> list[dict[str, Any]]:
        return [
            {
                'amount': Decimal('-100.00'),
                'description': 'Кофейня',
                'date': datetime(2024, 1, 1, 9, tzinfo=UTC),
                'row_position': 0,
            },
            {
                'amount': Decimal('-200.00'),
                'description': 'Магазин',
                'date': self.duplicate_date,
                'row_position': 1,
            },
        ]

    def _process(self) -> None:
        self.service._process_transactions(
            upload=self.upload,
            transactions=self._rows(),
            existing_categories=[],
        )

    def test_classifier_called_outside_row_transaction(self) -> None:
        test_depth = len(connection.atomic_blocks)

        self._process()

        self.assertEqual(self.classifier.atomic_depths, [test_depth] * 2)

    def test_rerun_over_imported_rows_skips_classifier(self) -> None:
        self._process()
        self.upload.processed_transactions = 0
        self.classifier.atomic_depths.clear()

        self.service._process_transactions(
            upload=self.upload,
            transactions=self._rows()[:1],
            existing_categories=[],
        )

        self.assertEqual(self.classifier.atomic_depths, [])
