"""Independent completeness assessment for selected accounts and dates."""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import (
    Account,
    AccountCoverageConfirmation,
)
from hasta_la_vista_money.finance_account.repositories.account_coverage_repository import (  # noqa: E501
    AccountCoverageRepository,
)
from hasta_la_vista_money.finance_account.services.coverage_service import (
    AccountCoverageService,
)
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.repositories.accounting_completeness_repository import (  # noqa: E501
    AccountingCompletenessRepository,
)
from hasta_la_vista_money.users.services.accounting_completeness import (
    AccountingCompletenessResult,
    AccountingCompletenessService,
)
from hasta_la_vista_money.users.services.statement_balance_verification import (
    FinalReconciliationBlock,
)


class _UnexplainedDiscrepancyProvider:
    def __init__(self, upload_id: int) -> None:
        self.upload_id = upload_id

    def final_reconciliation_block(
        self,
        *,
        user_id: int,
        account_ids: list[int],
        period_start: date,
        period_end: date,
    ) -> FinalReconciliationBlock:
        del user_id, account_ids, period_start, period_end
        return FinalReconciliationBlock(
            upload_ids=(self.upload_id,),
            reasons=('balance_unexplained_mismatch',),
        )


class AccountingCompletenessTest(TestCase):
    """Coverage, processing, problems and balances stay independent."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username='completeness')
        self.other = User.objects.create_user(username='completeness-other')
        self.account = Account.objects.create(
            user=self.user,
            name_account='Счёт RUB',
            currency='RUB',
        )
        self.coverage = AccountCoverageService(
            repository=AccountCoverageRepository(),
        )
        self.service = AccountingCompletenessService(
            coverage_service=self.coverage,
            repository=AccountingCompletenessRepository(),
        )
        self.period_start = date(2026, 1, 1)
        self.period_end = date(2026, 1, 31)

    def _upload(
        self,
        *,
        account: Account | None = None,
        status: str = BankStatementUpload.Status.COMPLETED,
        traceability_version: int = 0,
        verified_at: datetime | None = None,
        cleaned: bool = False,
    ) -> BankStatementUpload:
        return BankStatementUpload.objects.create(
            user=self.user,
            account=account or self.account,
            pdf_file='statement.pdf',
            status=status,
            processing_traceability_version=traceability_version,
            processing_verified_at=verified_at,
            retention_cleaned_at=timezone.now() if cleaned else None,
            statement_period_start=self.period_start,
            statement_period_end=self.period_end,
        )

    def _row(
        self,
        upload: BankStatementUpload,
        *,
        decision: str = BankStatementRow.Decision.PENDING,
        amount: Decimal | None = Decimal('100.00'),
        direction: str | None = BankStatementRow.TransactionType.EXPENSE,
        day: date | None = date(2026, 1, 15),
        reason: str = '',
        cleaned: bool = False,
    ) -> BankStatementRow:
        return BankStatementRow.objects.create(
            upload=upload,
            decision=decision,
            transaction_type=direction,
            amount=amount,
            bank_calendar_date=day,
            transaction_date=(
                datetime.combine(day, datetime.min.time(), tzinfo=UTC)
                if day is not None
                else None
            ),
            date_precision=(
                BankStatementRow.DatePrecision.DAY
                if day is not None
                else BankStatementRow.DatePrecision.UNKNOWN
            ),
            data_cleaned_at=timezone.now() if cleaned else None,
            decision_reason=reason,
        )

    def _confirm(
        self,
        start: date | None = None,
        end: date | None = None,
        *,
        account: Account | None = None,
        source: str = AccountCoverageConfirmation.Source.BANK,
        upload: BankStatementUpload | None = None,
    ) -> AccountCoverageConfirmation:
        return self.coverage.confirm(
            owner=self.user,
            account=account or self.account,
            period_start=start or self.period_start,
            period_end=end or self.period_end,
            source=source,
            statement_upload=upload,
        )

    def _assess(
        self,
        *,
        account_ids: Sequence[int] | None = None,
        period_start: date | None = None,
        period_end: date | None = None,
        balance_provider: Any | None = None,
    ) -> AccountingCompletenessResult:
        return self.service.assess(
            owner=self.user,
            account_ids=account_ids,
            period_start=period_start or self.period_start,
            period_end=period_end or self.period_end,
            balance_provider=balance_provider,
        )

    def test_legacy_utc_moment_uses_local_period_day(self) -> None:
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='legacy-period.pdf',
            status=BankStatementUpload.Status.COMPLETED,
        )
        legacy = BankStatementRow.objects.create(
            upload=upload,
            decision=BankStatementRow.Decision.PENDING,
            transaction_type=BankStatementRow.TransactionType.EXPENSE,
            amount=Decimal('10.00'),
            bank_calendar_date=None,
            transaction_date=datetime(
                2026,
                2,
                28,
                21,
                30,
                tzinfo=UTC,
            ),
            date_precision=BankStatementRow.DatePrecision.DATETIME,
        )
        explicit = BankStatementRow.objects.create(
            upload=upload,
            decision=BankStatementRow.Decision.DEFERRED,
            transaction_type=BankStatementRow.TransactionType.EXPENSE,
            amount=Decimal('20.00'),
            bank_calendar_date=date(2026, 2, 28),
            transaction_date=datetime(
                2026,
                2,
                28,
                21,
                30,
                tzinfo=UTC,
            ),
            date_precision=BankStatementRow.DatePrecision.DAY,
        )

        with timezone.override('Europe/Moscow'):
            march = self.service.assess(
                owner=self.user,
                account_ids=[self.account.pk],
                period_start=date(2026, 3, 1),
                period_end=date(2026, 3, 1),
            )
            february = self.service.assess(
                owner=self.user,
                account_ids=[self.account.pk],
                period_start=date(2026, 2, 28),
                period_end=date(2026, 2, 28),
            )

        self.assertEqual(march.accounts[0].unresolved_count, 1)
        self.assertEqual(february.accounts[0].unresolved_count, 1)
        self.assertTrue(legacy.pk)
        self.assertTrue(explicit.pk)

    def test_legacy_completed_without_rows_is_not_processing_proof(self):
        self._upload(status=BankStatementUpload.Status.COMPLETED)
        self._confirm()

        result = self._assess()
        account = result.accounts[0]

        self.assertFalse(account.processing_verified)
        self.assertFalse(account.can_finalize)
        self.assertIsNotNone(account.latest_upload)
        if account.latest_upload is None:
            self.fail('latest upload is required')
        self.assertEqual(
            account.latest_upload.reason_code,
            'legacy_no_saved_rows',
        )
        self.assertTrue(account.latest_upload.requires_reupload)
        self.assertIn(
            'processing_not_proven',
            [warning.code for warning in result.warnings],
        )

    def test_legacy_counts_and_saved_rows_do_not_prove_processing(self):
        upload = self._upload()
        upload.total_transactions = 1
        upload.processed_transactions = 1
        upload.income_count = 1
        upload.save(
            update_fields=[
                'total_transactions',
                'processed_transactions',
                'income_count',
            ],
        )
        self._row(upload, decision=BankStatementRow.Decision.NEW)
        self._confirm()

        result = self._assess()
        account = result.accounts[0]

        self.assertFalse(account.processing_verified)
        if account.latest_upload is None:
            self.fail('latest upload is required')
        self.assertEqual(
            account.latest_upload.reason_code,
            'legacy_untraceable_parser',
        )
        self.assertTrue(account.latest_upload.requires_reupload)

    def test_empty_statement_can_confirm_coverage_without_processing_proof(
        self,
    ):
        upload = self._upload()
        self._confirm(
            source=AccountCoverageConfirmation.Source.BANK,
            upload=upload,
        )

        result = self._assess()
        account = result.accounts[0]

        self.assertTrue(account.coverage.fully_covered)
        self.assertEqual(account.coverage.gaps, ())
        self.assertFalse(account.processing_verified)
        self.assertFalse(account.can_finalize)

    def test_new_traceable_processing_and_coverage_allow_finalizing(self):
        self._upload(
            traceability_version=1,
            verified_at=timezone.now(),
        )
        self._confirm()

        result = self._assess()
        account = result.accounts[0]

        self.assertTrue(account.processing_verified)
        self.assertTrue(account.coverage.fully_covered)
        self.assertTrue(account.can_finalize)
        self.assertTrue(result.can_finalize)
        self.assertFalse(account.balance.checked)
        self.assertFalse(account.balance.blocked)
        self.assertEqual(
            account.balance.reason,
            'balance_verification_not_integrated',
        )

    def test_manual_coverage_does_not_hide_a_deferred_problem(self):
        cash = Account.objects.create(
            user=self.user,
            name_account='Наличные',
            currency='RUB',
            type_account='CASH',
        )
        upload = self._upload(
            account=cash,
            traceability_version=1,
            verified_at=timezone.now(),
        )
        self._row(upload, decision=BankStatementRow.Decision.DEFERRED)
        self._confirm(
            account=cash,
            source=AccountCoverageConfirmation.Source.MANUAL,
        )

        result = self._assess(account_ids=[cash.pk])
        account = result.accounts[0]

        self.assertEqual(account.unresolved_count, 1)
        self.assertEqual(account.problems[0].code, 'deferred')
        self.assertFalse(account.can_finalize)
        self.assertFalse(result.can_finalize)

    def test_amounts_are_split_by_currency_and_direction(self):
        second = Account.objects.create(
            user=self.user,
            name_account='Счёт USD',
            currency='USD',
        )
        first_upload = self._upload(
            traceability_version=1,
            verified_at=timezone.now(),
        )
        second_upload = self._upload(
            account=second,
            traceability_version=1,
            verified_at=timezone.now(),
        )
        self._row(
            first_upload,
            amount=Decimal('100.00'),
            direction=BankStatementRow.TransactionType.INCOME,
        )
        self._row(
            first_upload,
            amount=Decimal('20.00'),
            direction=BankStatementRow.TransactionType.EXPENSE,
        )
        self._row(
            second_upload,
            amount=Decimal('5.00'),
            direction=BankStatementRow.TransactionType.EXPENSE,
        )
        self._row(first_upload, amount=None)
        self._confirm()
        self._confirm(account=second)

        result = self._assess()
        totals = {
            (item.currency, item.direction): item.amount
            for item in result.total_known_amounts
        }

        self.assertEqual(totals[('RUB', 'income')], Decimal('100.00'))
        self.assertEqual(totals[('RUB', 'expense')], Decimal('20.00'))
        self.assertEqual(totals[('USD', 'expense')], Decimal('5.00'))
        self.assertTrue(result.accounts[0].amounts.incomplete)
        self.assertEqual(result.accounts[0].amounts.unknown_count, 1)

    def test_excluded_rows_are_a_caveat_not_a_blocker(self):
        upload = self._upload(
            traceability_version=1,
            verified_at=timezone.now(),
        )
        self._row(
            upload,
            decision=BankStatementRow.Decision.EXCLUDED,
            amount=Decimal('30.00'),
            reason='Не операция',
        )
        self._confirm()

        result = self._assess()
        account = result.accounts[0]

        self.assertEqual(account.exclusions.count, 1)
        self.assertEqual(account.exclusions.reasons, ('Не операция',))
        self.assertEqual(
            account.exclusions.amounts[0].amount,
            Decimal('30.00'),
        )
        self.assertTrue(account.can_finalize)

    def test_retention_clears_amounts_and_creates_one_restore_problem(self):
        upload = self._upload(cleaned=True)
        self._row(
            upload,
            decision=BankStatementRow.Decision.EXPIRED,
            amount=None,
            day=None,
            cleaned=True,
        )
        self._row(
            upload,
            decision=BankStatementRow.Decision.EXPIRED,
            amount=None,
            day=None,
            cleaned=True,
        )
        self._confirm()

        result = self._assess()
        account = result.accounts[0]

        self.assertEqual(account.unresolved_count, 2)
        self.assertEqual(
            [(problem.code, problem.count) for problem in account.problems],
            [('restore_required', 1)],
        )
        self.assertTrue(account.amounts.incomplete)
        self.assertEqual(account.amounts.known, ())
        self.assertTrue(account.coverage.fully_covered)
        self.assertFalse(account.can_finalize)

    def test_unknown_balance_is_not_zero(self):
        self._upload(
            traceability_version=1,
            verified_at=timezone.now(),
        )
        self._confirm()

        result = self._assess()

        self.assertFalse(result.accounts[0].balance.checked)
        self.assertNotEqual(result.accounts[0].balance.reason, '0')
        self.assertTrue(result.can_finalize)

    def test_unexplained_discrepancy_blocks_despite_manual_coverage(self):
        upload = self._upload(
            traceability_version=1,
            verified_at=timezone.now(),
        )
        self._confirm(
            source=AccountCoverageConfirmation.Source.MANUAL,
        )

        result = self._assess(
            balance_provider=_UnexplainedDiscrepancyProvider(upload.pk),
        )

        self.assertFalse(result.can_finalize)
        self.assertTrue(result.accounts[0].balance.blocked)
        self.assertIn('balance_discrepancy', result.blockers)
        self.assertIn(
            'balance_discrepancy',
            [warning.code for warning in result.warnings],
        )

    def test_only_the_account_with_the_blocking_upload_is_blocked(self):
        blocked_upload = self._upload(
            traceability_version=1,
            verified_at=timezone.now(),
        )
        second = Account.objects.create(
            user=self.user,
            name_account='Чистый счёт',
            currency='RUB',
        )
        clean_upload = self._upload(
            account=second,
            traceability_version=1,
            verified_at=timezone.now(),
        )
        self._confirm()
        self._confirm(account=second)

        result = self._assess(
            balance_provider=_UnexplainedDiscrepancyProvider(
                blocked_upload.pk,
            ),
        )
        blocked, clean = result.accounts

        self.assertFalse(result.can_finalize)
        self.assertTrue(blocked.balance.blocked)
        self.assertFalse(blocked.can_finalize)
        self.assertFalse(clean.balance.blocked)
        self.assertTrue(clean.can_finalize)
        self.assertNotEqual(clean_upload.pk, blocked_upload.pk)
        self.assertNotIn(
            'balance_discrepancy',
            [
                warning.code
                for warning in result.warnings
                if warning.account_id == clean.account_id
            ],
        )

    def test_manual_bank_debit_coverage_is_allowed(self):
        upload = self._upload(
            traceability_version=1,
            verified_at=timezone.now(),
        )
        confirmation = self._confirm(
            source=AccountCoverageConfirmation.Source.MANUAL,
        )

        result = self._assess(balance_provider=None)

        self.assertEqual(
            confirmation.source,
            AccountCoverageConfirmation.Source.MANUAL,
        )
        self.assertTrue(result.accounts[0].coverage.fully_covered)
        self.assertTrue(result.accounts[0].can_finalize)
        self.assertIsNotNone(upload.pk)

    def test_owner_only_accounts(self):
        foreign = Account.objects.create(
            user=self.other,
            name_account='Чужой',
            currency='RUB',
        )

        with self.assertRaises(PermissionDenied):
            self._assess(account_ids=[foreign.pk])

        result = self._assess()
        self.assertEqual(
            [account.account_id for account in result.accounts],
            [self.account.pk],
        )

    def test_known_life_dates_clip_coverage(self):
        self.account.opened_on = date(2026, 1, 10)
        self.account.save(update_fields=['opened_on'])
        self._confirm(start=date(2026, 1, 1), end=date(2026, 1, 31))

        result = self._assess()
        account = result.accounts[0]

        self.assertEqual(account.coverage.intervals[0].start, date(2026, 1, 10))
        self.assertTrue(account.coverage.fully_covered)

    def test_unknown_row_date_stays_visible(self):
        upload = self._upload(
            traceability_version=1,
            verified_at=timezone.now(),
        )
        self._row(upload, day=None, amount=Decimal('50.00'))
        self._confirm()

        result = self._assess()
        account = result.accounts[0]

        self.assertEqual(account.unresolved_count, 1)
        self.assertTrue(account.amounts.incomplete)
        self.assertEqual(account.amounts.unknown_count, 1)

    def test_no_confidence_percentage_is_returned(self):
        self._confirm()
        result = self._assess()

        self.assertFalse(hasattr(result, 'confidence_percent'))
        self.assertNotIn('percent', result.__dataclass_fields__)

    def test_retention_does_not_cancel_confirmed_coverage(self):
        upload = self._upload(cleaned=True)
        self._confirm(
            source=AccountCoverageConfirmation.Source.BANK,
            upload=upload,
        )

        result = self._assess()

        self.assertTrue(result.accounts[0].coverage.fully_covered)

    def test_window_outside_known_life_is_not_a_false_gap(self):
        self.account.opened_on = date(2026, 3, 1)
        self.account.save(update_fields=['opened_on'])
        self._confirm(start=date(2026, 3, 1), end=date(2026, 3, 31))

        result = self.service.assess(
            owner=self.user,
            account_ids=[self.account.pk],
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        account = result.accounts[0]

        self.assertFalse(account.coverage_required)
        self.assertTrue(account.can_finalize)
