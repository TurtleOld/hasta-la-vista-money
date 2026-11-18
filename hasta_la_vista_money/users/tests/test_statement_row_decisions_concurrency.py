"""Concurrent defer/exclude/resume decisions on one statement row."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from threading import Barrier
from typing import Final, cast

from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import Transaction
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.protocols.services import (
    StatementMarkupServiceProtocol,
    StatementRowLinkServiceProtocol,
)
from hasta_la_vista_money.users.services.bank_statement_reconciliation import (
    ReconciliationDecisionConflictError,
)

BARRIER_TIMEOUT: Final = 10
FUTURE_TIMEOUT: Final = 30
# Bound every worker statement so a blocked DB thread cannot hang the suite.
LOCK_TIMEOUT: Final = '5s'
STATEMENT_TIMEOUT: Final = '15s'


class StatementRowDecisionConcurrencyTest(TransactionTestCase):
    """Two real connections race for one row; money must never move."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        self.user: User = User.objects.get(pk=1)
        self.account = Account.objects.create(
            user=self.user,
            name_account='РосДорБанк',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='rosdorbank.pdf',
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.row = BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type='expense',
            transaction_date=datetime(
                2026,
                3,
                1,
                12,
                tzinfo=timezone.get_current_timezone(),
            ),
            amount=Decimal('100.00'),
            description='ПЯТЁРОЧКА',
            source_ref='1-01.03.2026',
            source_row_position=1,
            kind='card',
            decision=BankStatementRow.Decision.PENDING,
        )

    def _run_together(
        self,
        *calls: Callable[[], object],
    ) -> list[Exception]:
        """Run each callable on its own connection after one barrier."""
        barrier = Barrier(len(calls))
        errors: list[Exception] = []

        def worker(call: Callable[[], object]) -> None:
            barrier.wait(timeout=BARRIER_TIMEOUT)
            try:
                self._bound_worker_statements()
                call()
            except Exception as error:
                errors.append(error)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            futures = [pool.submit(worker, call) for call in calls]
            for future in futures:
                future.result(timeout=FUTURE_TIMEOUT)
        return errors

    def _link_service(self) -> StatementRowLinkServiceProtocol:
        return cast(
            'StatementRowLinkServiceProtocol',
            ApplicationContainer().users.statement_row_link_service(),
        )

    def _markup_service(self) -> StatementMarkupServiceProtocol:
        return cast(
            'StatementMarkupServiceProtocol',
            ApplicationContainer().users.statement_markup_service(),
        )

    @staticmethod
    def _bound_worker_statements() -> None:
        """Cap lock and statement waits on this worker's own connection."""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('lock_timeout', %s, false)",
                [LOCK_TIMEOUT],
            )
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, false)",
                [STATEMENT_TIMEOUT],
            )

    def _assert_no_money(self) -> None:
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertFalse(Transaction.objects.exists())

    def _assert_counters(self, decision: str) -> None:
        self.upload.refresh_from_db()
        expected_awaiting = (
            1 if decision == BankStatementRow.Decision.DEFERRED else 0
        )
        self.assertEqual(
            self.upload.awaiting_decision_count,
            expected_awaiting,
        )
        expected_status = (
            BankStatementUpload.Status.COMPLETED_WITH_UNRESOLVED
            if expected_awaiting
            else BankStatementUpload.Status.COMPLETED
        )
        self.assertEqual(self.upload.status, expected_status)

    def test_concurrent_defer_and_exclude_leave_one_decision(self) -> None:
        row_id = self.row.pk
        user_id = self.user.pk

        errors = self._run_together(
            lambda: self._link_service().defer(row_id, user_id),
            lambda: self._link_service().exclude(
                row_id,
                user_id,
                'Служебная строка',
            ),
        )

        unexpected = [
            error
            for error in errors
            if not isinstance(error, ReconciliationDecisionConflictError)
        ]
        self.assertEqual(unexpected, [])
        self.row.refresh_from_db()
        self.assertIn(
            self.row.decision,
            {
                BankStatementRow.Decision.DEFERRED,
                BankStatementRow.Decision.EXCLUDED,
            },
        )
        audits = list(self.row.decision_audits.all())
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].decision, self.row.decision)
        self._assert_no_money()
        self._assert_counters(self.row.decision)

    def test_concurrent_repeat_defer_audits_once(self) -> None:
        row_id = self.row.pk
        user_id = self.user.pk

        errors = self._run_together(
            lambda: self._link_service().defer(row_id, user_id),
            lambda: self._link_service().defer(row_id, user_id),
        )

        self.assertEqual(errors, [])
        self.row.refresh_from_db()
        self.assertEqual(self.row.decision, BankStatementRow.Decision.DEFERRED)
        self.assertEqual(self.row.decision_audits.count(), 1)
        self._assert_no_money()
        self._assert_counters(BankStatementRow.Decision.DEFERRED)

    def test_legacy_markup_skip_and_defer_audit_once(self) -> None:
        BankStatementRow.objects.filter(pk=self.row.pk).update(
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
        )
        row_id = self.row.pk
        user_id = self.user.pk

        errors = self._run_together(
            lambda: self._markup_service().skip(row_id, user_id),
            lambda: self._link_service().defer(row_id, user_id),
        )

        self.assertEqual(errors, [])
        self.row.refresh_from_db()
        self.assertEqual(self.row.decision, BankStatementRow.Decision.DEFERRED)
        self.assertEqual(
            self.row.resume_decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertEqual(self.row.decision_audits.count(), 1)
        self._assert_no_money()
        self._assert_counters(BankStatementRow.Decision.DEFERRED)
