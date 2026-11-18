"""Repayment and ordinary transfer on one account pair must not deadlock."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from threading import Barrier
from typing import Final, cast

from django.db import connection
from django.test import TransactionTestCase

from config.containers import ApplicationContainer
from hasta_la_vista_money.constants import (
    ACCOUNT_TYPE_CREDIT_CARD,
    ACCOUNT_TYPE_DEBIT_CARD,
)
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.finance_account.services.transfer_service import (
    TransferService,
)
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    User,
)

BARRIER_TIMEOUT: Final = 10
FUTURE_TIMEOUT: Final = 30
LOCK_TIMEOUT: Final = '5s'
STATEMENT_TIMEOUT: Final = '15s'
WHEN = datetime(2026, 2, 9, 12, 0, tzinfo=UTC)
ROW_AMOUNT = Decimal('100.00')
ORDINARY_AMOUNT = Decimal('50.00')


class RepaymentRowTransferRaceTest(TransactionTestCase):
    """Sorted account locks serialize repayment and ordinary transfers."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='race-repayer',
            password='testpass123',  # nosec B106: test-only password
        )
        self.debit = self._account(ACCOUNT_TYPE_DEBIT_CARD)
        self.card = self._account(ACCOUNT_TYPE_CREDIT_CARD)
        self.assertLess(self.debit.pk, self.card.pk)
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.card,
            pdf_file='bank_statements/race-card.pdf',
        )
        self.row = BankStatementRow.objects.create(
            upload=self.upload,
            source_row_position=0,
            transaction_type=BankStatementRow.TransactionType.INCOME,
            transaction_date=WHEN,
            amount=ROW_AMOUNT,
            description='Перевод на карту',
            decision=BankStatementRow.Decision.NEEDS_TRANSFER,
        )

    def _account(self, type_account: str) -> Account:
        return Account.objects.create(
            user=self.user,
            name_account=type_account,
            type_account=type_account,
            balance=Decimal('1000.00'),
            currency='RUB',
        )

    @staticmethod
    def _service() -> TransferService:
        return cast(
            'TransferService',
            ApplicationContainer().finance_account.transfer_service(),
        )

    def _repayment(self) -> tuple[str, int]:
        transfer = self._service().transfer_money(
            from_account=self.debit,
            to_account=self.card,
            amount=ROW_AMOUNT,
            user=self.user,
            exchange_date=WHEN,
            statement_row_id=self.row.pk,
        )
        return 'repayment', transfer.pk

    def _ordinary(self) -> tuple[str, int]:
        transfer = self._service().transfer_money(
            from_account=self.debit,
            to_account=self.card,
            amount=ORDINARY_AMOUNT,
            user=self.user,
            exchange_date=WHEN,
        )
        return 'ordinary', transfer.pk

    def _run_together(
        self,
        *calls: Callable[[], tuple[str, int]],
    ) -> tuple[list[tuple[str, int]], list[Exception]]:
        barrier = Barrier(len(calls))
        results: list[tuple[str, int]] = []
        errors: list[Exception] = []

        def worker(call: Callable[[], tuple[str, int]]) -> None:
            barrier.wait(timeout=BARRIER_TIMEOUT)
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT set_config('lock_timeout', %s, false)",
                        [LOCK_TIMEOUT],
                    )
                    cursor.execute(
                        "SELECT set_config('statement_timeout', %s, false)",
                        [STATEMENT_TIMEOUT],
                    )
                results.append(call())
            except Exception as error:
                errors.append(error)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            futures = [pool.submit(worker, call) for call in calls]
            for future in futures:
                future.result(timeout=FUTURE_TIMEOUT)
        return results, errors

    def test_repayment_against_ordinary_transfer_keeps_outcomes(
        self,
    ) -> None:
        results, errors = self._run_together(self._repayment, self._ordinary)

        self.assertEqual(errors, [])
        self.assertEqual(
            {name for name, _pk in results},
            {'repayment', 'ordinary'},
        )
        transfers = TransferMoneyLog.objects.order_by('pk')
        self.assertEqual(transfers.count(), 2)
        self.debit.refresh_from_db()
        self.card.refresh_from_db()
        self.row.refresh_from_db()
        self.assertEqual(
            self.debit.balance,
            Decimal('1000.00') - ROW_AMOUNT - ORDINARY_AMOUNT,
        )
        self.assertEqual(
            self.card.balance,
            Decimal('1000.00') + ROW_AMOUNT + ORDINARY_AMOUNT,
        )
        repayment_pk = next(pk for name, pk in results if name == 'repayment')
        self.assertEqual(
            self.row.decision,
            BankStatementRow.Decision.TRANSFERRED,
        )
        self.assertEqual(self.row.transfer_id, repayment_pk)
        self.assertTrue(
            transfers.filter(
                pk=repayment_pk,
                amount=ROW_AMOUNT,
            ).exists(),
        )
        self.assertTrue(
            transfers.filter(amount=ORDINARY_AMOUNT).exists(),
        )
