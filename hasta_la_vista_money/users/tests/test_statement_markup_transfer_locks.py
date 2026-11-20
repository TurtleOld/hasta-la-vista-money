"""Own-account transfer markup locks accounts in sorted order first."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from threading import Barrier
from typing import TYPE_CHECKING, Final, cast
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, TransactionTestCase

from config.containers import ApplicationContainer
from hasta_la_vista_money.constants import (
    ACCOUNT_TYPE_CREDIT_CARD,
    ACCOUNT_TYPE_DEBIT_CARD,
)
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.users.models import (
    BankStatementDecisionAudit,
    BankStatementRow,
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.services.statement_markup import (
    StatementMarkupConflictError,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.services.transfer_service import (
        TransferService,
    )

BARRIER_TIMEOUT: Final = 10
FUTURE_TIMEOUT: Final = 30
LOCK_TIMEOUT: Final = '5s'
STATEMENT_TIMEOUT: Final = '15s'
WHEN = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)
AMOUNT = Decimal('100.00')


class TransferLockFixture:
    """Two numbered accounts and one own-transfer row on each."""

    def _account(
        self,
        user: User,
        type_account: str,
        number: str,
    ) -> Account:
        return Account.objects.create(
            user=user,
            name_account=number,
            type_account=type_account,
            balance=Decimal('1000.00'),
            currency='RUB',
            account_number=number,
        )

    def _own_row(
        self,
        account: Account,
        counterparty: str,
        position: int,
    ) -> BankStatementRow:
        upload = BankStatementUpload.objects.create(
            user=account.user,
            account=account,
            pdf_file=f'bank_statements/lock-{position}.pdf',
        )
        return BankStatementRow.objects.create(
            upload=upload,
            source_row_position=position,
            transaction_type=BankStatementRow.TransactionType.EXPENSE,
            transaction_date=WHEN,
            amount=AMOUNT,
            description='Свой перевод',
            kind='own_c2c',
            counterparty_account=counterparty,
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
        )


class StatementTransferLockRaceTest(TransactionTestCase, TransferLockFixture):
    """Opposite own-transfer rows acquire both accounts in pk order."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='own-transfer-race',
            password='test-only-secret',
        )
        self.left = self._account(
            self.user,
            ACCOUNT_TYPE_DEBIT_CARD,
            '40817810000000000001',
        )
        self.right = self._account(
            self.user,
            ACCOUNT_TYPE_CREDIT_CARD,
            '40817810000000000002',
        )
        self.assertLess(self.left.pk, self.right.pk)
        self.left_row = self._own_row(
            self.left,
            '40817810000000000002',
            0,
        )
        self.right_row = self._own_row(
            self.right,
            '40817810000000000001',
            1,
        )

    @staticmethod
    def _bound_worker_statements() -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('lock_timeout', %s, false)",
                [LOCK_TIMEOUT],
            )
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, false)",
                [STATEMENT_TIMEOUT],
            )

    def _run_together(
        self,
        *calls: Callable[[], object],
    ) -> list[Exception]:
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

    def _post(self, row: BankStatementRow) -> None:
        ApplicationContainer().users.statement_markup_service().post_transfer(
            row.pk,
            self.user.pk,
            None,
        )

    def test_opposite_rows_do_not_deadlock_and_keep_one_transfer_each(
        self,
    ) -> None:
        errors = self._run_together(
            lambda: self._post(self.left_row),
            lambda: self._post(self.right_row),
        )

        self.assertEqual(errors, [])
        self.left.refresh_from_db()
        self.right.refresh_from_db()
        self.left_row.refresh_from_db()
        self.right_row.refresh_from_db()
        self.assertEqual(self.left.balance, Decimal('1000.00'))
        self.assertEqual(self.right.balance, Decimal('1000.00'))
        self.assertEqual(TransferMoneyLog.objects.count(), 2)
        self.assertEqual(
            self.left_row.decision,
            BankStatementRow.Decision.TRANSFERRED,
        )
        self.assertEqual(
            self.right_row.decision,
            BankStatementRow.Decision.TRANSFERRED,
        )
        self.assertNotEqual(
            self.left_row.transfer_id,
            self.right_row.transfer_id,
        )
        self.assertEqual(
            BankStatementDecisionAudit.objects.filter(
                row__in=(self.left_row, self.right_row),
                decision=BankStatementRow.Decision.TRANSFERRED,
            ).count(),
            2,
        )

    def test_markup_transfer_against_ordinary_transfer_keeps_one_each(
        self,
    ) -> None:
        def ordinary() -> TransferMoneyLog:
            transfer_service = cast(
                'TransferService',
                ApplicationContainer().finance_account.transfer_service(),
            )
            return transfer_service.transfer_money(
                from_account=self.left,
                to_account=self.right,
                amount=Decimal('50.00'),
                user=self.user,
                exchange_date=WHEN,
            )

        errors = self._run_together(
            lambda: self._post(self.left_row),
            ordinary,
        )

        self.assertEqual(errors, [])
        self.left.refresh_from_db()
        self.right.refresh_from_db()
        self.left_row.refresh_from_db()
        self.assertEqual(self.left.balance, Decimal('850.00'))
        self.assertEqual(self.right.balance, Decimal('1150.00'))
        self.assertEqual(TransferMoneyLog.objects.count(), 2)
        self.assertEqual(
            self.left_row.decision,
            BankStatementRow.Decision.TRANSFERRED,
        )
        self.assertIsNotNone(self.left_row.transfer_id)

    def test_foreign_owner_cannot_post_the_row(self) -> None:
        stranger = User.objects.create_user(username='stranger-owner')
        service = ApplicationContainer().users.statement_markup_service()

        with self.assertRaises(BankStatementRow.DoesNotExist):
            service.post_transfer(self.left_row.pk, stranger.pk, None)

        self.left_row.refresh_from_db()
        self.assertEqual(
            self.left_row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertFalse(TransferMoneyLog.objects.exists())


class StatementTransferCounterpartyTest(TestCase, TransferLockFixture):
    """Missing or changed counterparties fail before any money moves."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username='own-transfer-pair')
        self.own = self._account(
            self.user,
            ACCOUNT_TYPE_DEBIT_CARD,
            '40817810000000000001',
        )
        self.other = self._account(
            self.user,
            ACCOUNT_TYPE_DEBIT_CARD,
            '40817810000000000002',
        )
        self.service = ApplicationContainer().users.statement_markup_service()

    def _row(self, counterparty: str) -> BankStatementRow:
        return self._own_row(self.own, counterparty, 0)

    def _assert_failed_closed(self, row: BankStatementRow) -> None:
        row.refresh_from_db()
        self.own.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertIsNone(row.transfer_id)
        self.assertFalse(TransferMoneyLog.objects.exists())
        self.assertEqual(self.own.balance, Decimal('1000.00'))
        self.assertEqual(self.other.balance, Decimal('1000.00'))

    def test_unknown_number_without_a_chosen_account_fails_closed(self) -> None:
        row = self._row('40817810000000000099')

        with self.assertRaises(StatementMarkupConflictError):
            self.service.post_transfer(row.pk, self.user.pk, None)

        self._assert_failed_closed(row)

    def test_foreign_number_cannot_be_bound_to_the_chosen_account(
        self,
    ) -> None:
        number = '40817810000000000099'
        stranger = User.objects.create_user(username='foreign-number')
        Account.objects.create(
            user=stranger,
            name_account='Чужой',
            balance=Decimal('0.00'),
            currency='RUB',
            account_number=number,
        )
        row = self._row(number)

        with self.assertRaises(StatementMarkupConflictError):
            self.service.post_transfer(row.pk, self.user.pk, self.other.pk)

        self._assert_failed_closed(row)

    def test_changed_account_number_under_locks_fails_closed(self) -> None:
        number = '40817810000000000099'
        row = self._row(number)
        late = self._account(self.user, ACCOUNT_TYPE_DEBIT_CARD, number)
        repository = self.service._account_repository

        with (
            patch.object(
                repository,
                'get_by_user_and_account_number',
                side_effect=[None, late],
            ),
            self.assertRaises(StatementMarkupConflictError),
        ):
            self.service.post_transfer(row.pk, self.user.pk, self.other.pk)

        row.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertIsNone(row.transfer_id)
        self.assertEqual(
            self.other.account_number,
            '40817810000000000002',
        )
        self.assertFalse(TransferMoneyLog.objects.exists())

    def test_unbound_number_is_written_only_after_successful_locks(
        self,
    ) -> None:
        number = '40817810000000000099'
        self.other.account_number = None
        self.other.save(update_fields=['account_number'])
        row = self._row(number)

        self.service.post_transfer(row.pk, self.user.pk, self.other.pk)

        self.other.refresh_from_db()
        row.refresh_from_db()
        self.assertEqual(self.other.account_number, number)
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.TRANSFERRED,
        )
        self.assertIsNotNone(row.transfer_id)
