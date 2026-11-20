"""Public lifecycle hooks that recheck coverage after real changes."""

from datetime import UTC, date, datetime
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import (
    Account,
    AccountCoverageConfirmation,
)
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    User,
)


class CoverageInvalidationLifecycleTest(TestCase):
    """Coverage is rechecked only for a real problem or influencing change."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='coverage-invalidation',
            password='test-only-password',  # nosec B106
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Дебетовый счёт',
            currency='RUB',
            opened_on=date(2026, 1, 1),
            closed_on=date(2026, 1, 31),
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='statement.pdf',
            statement_period_start=date(2026, 1, 1),
            statement_period_end=date(2026, 1, 31),
        )
        self.coverage = (
            ApplicationContainer().finance_account.account_coverage_service()
        )
        self.coverage.confirm(
            owner=self.user,
            account=self.account,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            source=AccountCoverageConfirmation.Source.BANK,
        )

    def _row(
        self,
        *,
        decision: str = BankStatementRow.Decision.PENDING,
        day: date | None = date(2026, 1, 15),
        transaction: Transaction | None = None,
    ) -> BankStatementRow:
        return BankStatementRow.objects.create(
            upload=self.upload,
            decision=decision,
            transaction_type=BankStatementRow.TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            transaction_date=(
                datetime.combine(day, datetime.min.time(), tzinfo=UTC)
                if day is not None
                else None
            ),
            bank_calendar_date=day,
            date_precision=(
                BankStatementRow.DatePrecision.DAY
                if day is not None
                else BankStatementRow.DatePrecision.UNKNOWN
            ),
            transaction=transaction,
        )

    def _summary(self):
        return self.coverage.summary(
            account=self.account,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )

    def _category(self) -> Category:
        return Category.objects.create(
            user=self.user,
            name='Расход',
            type=TransactionType.EXPENSE,
        )

    def _transaction(self) -> Transaction:
        return Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self._category(),
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=datetime(2026, 1, 15, 12, tzinfo=UTC),
            bank_calendar_date=date(2026, 1, 15),
        )

    def test_deferring_a_row_rechecks_its_exact_bank_day(self):
        row = self._row()
        link_service = ApplicationContainer().users.statement_row_link_service()

        link_service.defer(row.pk, self.user.pk)
        summary = self._summary()
        row.refresh_from_db()

        self.assertEqual(row.decision, BankStatementRow.Decision.DEFERRED)
        self.assertEqual(
            [(item.start, item.end) for item in summary.intervals],
            [
                (date(2026, 1, 1), date(2026, 1, 14)),
                (date(2026, 1, 16), date(2026, 1, 31)),
            ],
        )
        self.assertEqual(
            [(gap.start, gap.end) for gap in summary.gaps],
            [(date(2026, 1, 15), date(2026, 1, 15))],
        )
        self.assertEqual(
            summary.invalidated[0].recheck_reason,
            'row_deferred',
        )

    def test_resuming_a_reopened_problem_invalidates_again(self):
        row = self._row()
        link_service = ApplicationContainer().users.statement_row_link_service()
        link_service.defer(row.pk, self.user.pk)
        self.coverage.confirm(
            owner=self.user,
            account=self.account,
            period_start=date(2026, 1, 15),
            period_end=date(2026, 1, 15),
            source=AccountCoverageConfirmation.Source.BANK,
        )

        link_service.resume(row.pk, self.user.pk)
        summary = self._summary()

        self.assertEqual(
            [(gap.start, gap.end) for gap in summary.gaps],
            [(date(2026, 1, 15), date(2026, 1, 15))],
        )
        self.assertIn(
            'row_problem_resumed',
            {item.recheck_reason for item in summary.invalidated},
        )

    def test_deleting_a_linked_movement_rechecks_the_reopened_row(self):
        transaction = self._transaction()
        row = self._row(
            decision=BankStatementRow.Decision.LINKED,
            transaction=transaction,
        )
        link_service = ApplicationContainer().users.statement_row_link_service()

        link_service.release_linked_rows(transaction)
        summary = self._summary()
        row.refresh_from_db()

        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        self.assertEqual(
            [(gap.start, gap.end) for gap in summary.gaps],
            [(date(2026, 1, 15), date(2026, 1, 15))],
        )
        self.assertEqual(
            summary.invalidated[0].recheck_reason,
            'movement_reopened',
        )

    def test_import_problem_rechecks_the_document_period(self):
        self._row(day=None)
        import_service = (
            ApplicationContainer().users.bank_statement_import_service()
        )
        generation = import_service.capture_generation(self.upload)

        import_service.finalize_import(
            self.upload,
            generation,
            closing_balance=None,
        )
        summary = self._summary()

        self.assertEqual(summary.intervals, ())
        self.assertEqual(
            [(gap.start, gap.end) for gap in summary.gaps],
            [(date(2026, 1, 1), date(2026, 1, 31))],
        )
        self.assertEqual(
            summary.invalidated[0].recheck_reason,
            'import_problem',
        )

    def test_owner_life_date_change_rechecks_only_moved_boundary(self):
        self.client = Client()
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('finance_account:change', args=[self.account.pk]),
            {
                'name_account': self.account.name_account,
                'type_account': self.account.type_account,
                'bank': self.account.bank_id,
                'currency': self.account.currency,
                'opened_on': '2026-01-10',
                'closed_on': '2026-01-31',
            },
        )
        summary = self._summary()
        self.account.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.account.opened_on, date(2026, 1, 10))
        self.assertEqual(
            [(item.start, item.end) for item in summary.intervals],
            [(date(2026, 1, 10), date(2026, 1, 31))],
        )
        self.assertEqual(
            [(gap.start, gap.end) for gap in summary.gaps],
            [(date(2026, 1, 1), date(2026, 1, 9))],
        )
        self.assertEqual(
            summary.invalidated[0].recheck_reason,
            'account_life_changed',
        )

    def test_financial_movement_change_rechecks_exact_bank_day(self):
        transaction = self._transaction()
        Transaction.objects.filter(pk=transaction.pk).update(
            amount=Decimal('250.00'),
        )

        affected = self.coverage.invalidate_for_movement_change(
            account=self.account,
            changed_on=date(2026, 1, 15),
        )
        summary = self._summary()

        self.assertEqual(affected, 1)
        self.assertEqual(
            [(gap.start, gap.end) for gap in summary.gaps],
            [(date(2026, 1, 15), date(2026, 1, 15))],
        )

    def test_category_only_change_does_not_invalidate_coverage(self):
        transaction = self._transaction()
        other_category = Category.objects.create(
            user=self.user,
            name='Другая категория',
            type=TransactionType.EXPENSE,
        )
        transaction.category = other_category
        transaction.save(update_fields=['category'])

        summary = self._summary()

        self.assertTrue(summary.fully_covered)
        self.assertEqual(summary.invalidated, ())

    def test_container_override_is_used_by_row_link_service(self):
        calls: list[tuple[int, str]] = []

        class _Recorder:
            def invalidate_for_row_problem(self, *, row, reason):
                calls.append((row.pk, reason))
                return 1

        container = ApplicationContainer()
        container.finance_account.account_coverage_service.override(
            _Recorder(),
        )
        row = self._row()
        link_service = container.users.statement_row_link_service()

        link_service.defer(row.pk, self.user.pk)

        self.assertEqual(calls, [(row.pk, 'row_deferred')])

    def test_retention_and_plain_overlap_do_not_invalidate(self):
        self.upload.retention_cleaned_at = timezone.now()
        self.upload.save(update_fields=['retention_cleaned_at'])
        BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='overlap.pdf',
            statement_period_start=date(2026, 1, 10),
            statement_period_end=date(2026, 1, 20),
        )

        summary = self._summary()

        self.assertTrue(summary.fully_covered)
        self.assertEqual(summary.invalidated, ())
