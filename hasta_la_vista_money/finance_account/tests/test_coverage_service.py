"""Coverage confirmations, interval union/gaps and invalidation."""

from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

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
from hasta_la_vista_money.system.models import AuditLog
from hasta_la_vista_money.users.models import BankStatementUpload, User


class CoverageModelTest(TestCase):
    """The small confirmation model keeps inclusive calendar bounds."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username='coverage-model')
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной',
            currency='RUB',
        )

    def test_confirmation_stores_inclusive_period(self) -> None:
        confirmation = AccountCoverageConfirmation.objects.create(
            account=self.account,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            source=AccountCoverageConfirmation.Source.MANUAL,
            confirmed_by=self.user,
        )

        self.assertEqual(confirmation.period_start, date(2026, 1, 1))
        self.assertEqual(confirmation.period_end, date(2026, 1, 31))
        self.assertFalse(confirmation.needs_recheck)

    def test_database_rejects_reversed_period(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccountCoverageConfirmation.objects.create(
                account=self.account,
                period_start=date(2026, 2, 1),
                period_end=date(2026, 1, 1),
                source=AccountCoverageConfirmation.Source.MANUAL,
                confirmed_by=self.user,
            )

    def test_confirmations_survive_statement_data_cleanup(self) -> None:
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='statement.pdf',
            status=BankStatementUpload.Status.COMPLETED,
            retention_cleaned_at='2026-01-01T00:00:00Z',
        )
        confirmation = AccountCoverageConfirmation.objects.create(
            account=self.account,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            source=AccountCoverageConfirmation.Source.BANK,
            statement_upload=upload,
            confirmed_by=self.user,
        )

        upload.refresh_from_db()
        self.assertIsNotNone(upload.retention_cleaned_at)
        self.assertTrue(
            AccountCoverageConfirmation.objects.filter(
                pk=confirmation.pk,
            ).exists(),
        )


class CoverageServiceTest(TestCase):
    """The service owns confirmation, interval math and invalidation."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username='coverage-service')
        self.other = User.objects.create_user(username='coverage-other')
        self.account = Account.objects.create(
            user=self.user,
            name_account='Счёт',
            currency='RUB',
        )
        self.account_two = Account.objects.create(
            user=self.user,
            name_account='Второй',
            currency='RUB',
        )
        self.service = AccountCoverageService(
            repository=AccountCoverageRepository(),
        )

    def _confirm(
        self,
        start: date,
        end: date,
        *,
        account: Account | None = None,
        source: str = AccountCoverageConfirmation.Source.BANK,
    ) -> AccountCoverageConfirmation:
        return self.service.confirm(
            owner=self.user,
            account=account or self.account,
            period_start=start,
            period_end=end,
            source=source,
        )

    def test_adjacent_and_overlapping_confirmations_merge(self) -> None:
        self._confirm(date(2026, 1, 1), date(2026, 1, 10))
        self._confirm(date(2026, 1, 11), date(2026, 1, 20))
        self._confirm(date(2026, 1, 15), date(2026, 1, 25))

        summary = self.service.summary(
            account=self.account,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )

        self.assertEqual(len(summary.intervals), 1)
        self.assertEqual(summary.intervals[0].start, date(2026, 1, 1))
        self.assertEqual(summary.intervals[0].end, date(2026, 1, 25))
        self.assertEqual(
            [(gap.start, gap.end) for gap in summary.gaps],
            [(date(2026, 1, 26), date(2026, 1, 31))],
        )
        self.assertFalse(summary.fully_covered)

    def test_gaps_are_computed_per_account(self) -> None:
        self._confirm(date(2026, 1, 1), date(2026, 1, 5))
        self._confirm(
            date(2026, 1, 20),
            date(2026, 1, 31),
            account=self.account_two,
        )

        first = self.service.summary(
            account=self.account,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        second = self.service.summary(
            account=self.account_two,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )

        self.assertEqual(
            [(gap.start, gap.end) for gap in first.gaps],
            [(date(2026, 1, 6), date(2026, 1, 31))],
        )
        self.assertEqual(
            [(gap.start, gap.end) for gap in second.gaps],
            [(date(2026, 1, 1), date(2026, 1, 19))],
        )

    def test_known_life_dates_clip_but_unknown_do_not(self) -> None:
        self._confirm(date(2026, 1, 1), date(2026, 1, 31))
        self.account.opened_on = date(2026, 1, 5)
        self.account.closed_on = date(2026, 1, 20)
        self.account.save(update_fields=['opened_on', 'closed_on'])

        clipped = self.service.summary(
            account=self.account,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )

        self.assertEqual(
            [(item.start, item.end) for item in clipped.intervals],
            [(date(2026, 1, 5), date(2026, 1, 20))],
        )
        self.assertEqual(clipped.gaps, ())

        self.account.opened_on = None
        self.account.closed_on = None
        self.account.save(update_fields=['opened_on', 'closed_on'])
        unknown = self.service.summary(
            account=self.account,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        self.assertEqual(
            [(item.start, item.end) for item in unknown.intervals],
            [(date(2026, 1, 1), date(2026, 1, 31))],
        )

    def test_precise_invalidation_splits_and_keeps_reason(self) -> None:
        confirmation = self._confirm(date(2026, 1, 1), date(2026, 1, 31))

        affected = self.service.invalidate(
            owner=self.user,
            account=self.account,
            affected_start=date(2026, 1, 12),
            affected_end=date(2026, 1, 14),
            reason='Ошибка разбора строки',
        )

        summary = self.service.summary(
            account=self.account,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        self.assertEqual(len(affected), 1)
        self.assertEqual(
            [(item.start, item.end) for item in summary.intervals],
            [
                (date(2026, 1, 1), date(2026, 1, 11)),
                (date(2026, 1, 15), date(2026, 1, 31)),
            ],
        )
        self.assertEqual(
            [(gap.start, gap.end) for gap in summary.gaps],
            [(date(2026, 1, 12), date(2026, 1, 14))],
        )
        invalid = AccountCoverageConfirmation.objects.get(
            pk=confirmation.pk,
        )
        self.assertTrue(invalid.needs_recheck)
        self.assertEqual(invalid.recheck_reason, 'Ошибка разбора строки')
        self.assertEqual(invalid.period_start, date(2026, 1, 12))
        self.assertEqual(invalid.period_end, date(2026, 1, 14))
        self.assertTrue(
            AuditLog.objects.filter(
                model_name='finance_account.AccountCoverageConfirmation',
                object_pk=str(confirmation.pk),
            ).exists(),
        )

    def test_unknown_invalidation_scope_rechecks_whole_period(self) -> None:
        self._confirm(date(2026, 1, 1), date(2026, 1, 31))

        self.service.invalidate(
            owner=self.user,
            account=self.account,
            affected_start=None,
            affected_end=None,
            reason='Точный интервал неизвестен',
        )

        summary = self.service.summary(
            account=self.account,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        self.assertEqual(summary.intervals, ())
        self.assertEqual(len(summary.invalidated), 1)
        self.assertEqual(
            summary.invalidated[0].recheck_reason,
            'Точный интервал неизвестен',
        )

    def test_new_overlapping_upload_does_not_cancel_coverage(self) -> None:
        self._confirm(date(2026, 1, 1), date(2026, 1, 31))
        BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='new.pdf',
            status=BankStatementUpload.Status.COMPLETED,
        )

        summary = self.service.summary(
            account=self.account,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        self.assertTrue(summary.fully_covered)

    def test_bank_source_requires_upload_of_the_same_account(self) -> None:
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account_two,
            pdf_file='other.pdf',
        )

        with self.assertRaises(ValidationError):
            self.service.confirm(
                owner=self.user,
                account=self.account,
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                source=AccountCoverageConfirmation.Source.BANK,
                statement_upload=upload,
            )
        self.assertFalse(AccountCoverageConfirmation.objects.exists())

    def test_owner_only_access(self) -> None:
        with self.assertRaises(PermissionDenied):
            self.service.confirm(
                owner=self.other,
                account=self.account,
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                source=AccountCoverageConfirmation.Source.MANUAL,
            )

    def test_reversed_manual_period_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self._confirm(date(2026, 2, 1), date(2026, 1, 1))

    def test_manual_source_allowed_for_cash(self) -> None:
        cash = Account.objects.create(
            user=self.user,
            name_account='Наличные',
            currency='RUB',
            type_account='CASH',
        )
        confirmation = self._confirm(
            date(2026, 1, 1),
            date(2026, 1, 31),
            account=cash,
            source=AccountCoverageConfirmation.Source.MANUAL,
        )

        self.assertEqual(
            confirmation.source,
            AccountCoverageConfirmation.Source.MANUAL,
        )
        self.assertIsNone(confirmation.statement_upload)

    def test_manual_source_rejected_for_bank_account(self) -> None:
        with self.assertRaises(ValidationError):
            self._confirm(
                date(2026, 1, 1),
                date(2026, 1, 31),
                source=AccountCoverageConfirmation.Source.MANUAL,
            )
