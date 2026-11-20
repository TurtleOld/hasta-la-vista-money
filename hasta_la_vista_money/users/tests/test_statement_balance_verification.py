"""Historical bank balance verification and its final-reconciliation guard."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.repositories import (
    AccountRepository,
    TransferMoneyLogRepository,
)
from hasta_la_vista_money.finance_account.services.balance_service import (
    BalanceService,
)
from hasta_la_vista_money.system.models import AuditLog
from hasta_la_vista_money.transactions.commands import (
    UpdateTransactionCommand,
)
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.factories import UserFactory
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.repositories.statement_balance_verification_repository import (  # noqa: E501
    StatementBalanceVerificationRepository,
)
from hasta_la_vista_money.users.repositories.statement_row_repository import (
    StatementRowRepository,
)
from hasta_la_vista_money.users.services.statement_balance_verification import (
    REASON_AVAILABLE_CREDIT_UNKNOWN,
    REASON_BANK_BALANCE_MISSING,
    REASON_DATA_CLEANED,
    REASON_DAY_TIMEZONE_UNKNOWN,
    REASON_KIND_UNKNOWN,
    REASON_MOVEMENT_CHANGED,
    REASON_NOT_CONFIGURED,
    REASON_UNRESOLVED_ROWS,
    STATUS_MISMATCH,
    STATUS_STALE,
    STATUS_UNKNOWN,
    STATUS_VERIFIED,
    StatementBalanceVerificationService,
    mark_balance_checks_stale,
)
from hasta_la_vista_money.users.services.statement_markup import (
    StatementMarkupService,
)

MOSCOW = ZoneInfo('Europe/Moscow')
BALANCE_DAY = date(2026, 4, 10)


class StatementBalanceVerificationTestCase(TestCase):
    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.account = Account.objects.create(
            user=self.user,
            name_account='Банк',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        container = ApplicationContainer()
        self.service = StatementBalanceVerificationService(
            repository=StatementBalanceVerificationRepository(),
            balance_history_service=(
                container.finance_account.balance_history_service()
            ),
        )

    def _upload(self, **kwargs: object) -> BankStatementUpload:
        values: dict[str, object] = {
            'user': self.user,
            'account': self.account,
            'pdf_file': '',
            'file_hash': f'hash-{BankStatementUpload.objects.count()}',
            'statement_closing_balance': Decimal('800.00'),
            'statement_balance_date': BALANCE_DAY,
            'statement_balance_kind': (BankStatementUpload.BalanceKind.CLOSING),
            'statement_balance_timezone': 'Europe/Moscow',
        }
        values.update(kwargs)
        return BankStatementUpload.objects.create(**values)

    def _transaction(
        self,
        amount: str,
        moment: datetime,
        transaction_type: str = TransactionType.INCOME,
        category: Category | None = None,
        account: Account | None = None,
    ) -> Transaction:
        if category is None:
            category = Category.objects.create(
                user=self.user,
                name=f'Категория {Transaction.objects.count()}',
                type=transaction_type,
            )
        return Transaction.objects.create(
            user=self.user,
            account=account or self.account,
            category=category,
            type=transaction_type,
            amount=Decimal(amount),
            date=moment,
        )

    def _later_income(self) -> Transaction:
        return self._transaction(
            '200.00',
            datetime(2026, 4, 11, 12, 0, tzinfo=UTC),
        )


class VerificationResultTests(StatementBalanceVerificationTestCase):
    def test_closing_day_matches_historical_balance(self) -> None:
        self._later_income()
        upload = self._upload()

        result = self.service.verify(upload.pk, self.user.pk)

        self.assertEqual(result.status, STATUS_VERIFIED)
        self.assertEqual(result.last_result, STATUS_VERIFIED)
        self.assertEqual(result.bank_balance, Decimal('800.00'))
        self.assertEqual(result.app_balance, Decimal('800.00'))
        self.assertEqual(result.difference, Decimal('0.00'))
        self.assertFalse(result.unexplained_mismatch)
        self.assertFalse(result.blocks_final_reconciliation)
        upload.refresh_from_db()
        self.assertEqual(upload.account_balance_after, Decimal('800.00'))
        self.assertEqual(upload.balance_discrepancy, Decimal('0.00'))

    def test_closing_includes_same_day_movement(self) -> None:
        self._transaction(
            '200.00',
            datetime(2026, 4, 10, 12, 0, tzinfo=UTC),
        )
        upload = self._upload(statement_closing_balance=Decimal('1000.00'))

        result = self.service.verify(upload.pk, self.user.pk)

        self.assertEqual(result.status, STATUS_VERIFIED)

    def test_later_posting_is_undone_at_the_bank_moment(self) -> None:
        transaction = self._later_income()
        upload = self._upload()
        first = self.service.verify(upload.pk, self.user.pk)
        self.assertEqual(first.status, STATUS_VERIFIED)
        self._transaction(
            '100.00',
            datetime(2026, 4, 12, 12, 0, tzinfo=UTC),
        )

        result = self.service.verify(upload.pk, self.user.pk)

        self.assertEqual(result.status, STATUS_MISMATCH)
        self.assertEqual(result.app_balance, Decimal('700.00'))
        self.assertTrue(result.blocks_final_reconciliation)
        self.assertEqual(Transaction.objects.count(), 2)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertIsNotNone(transaction.pk)

    def test_opening_balance_is_start_of_the_day(self) -> None:
        self._transaction(
            '200.00',
            datetime(2026, 4, 10, 12, 0, tzinfo=UTC),
        )
        upload = self._upload(
            statement_balance_kind=BankStatementUpload.BalanceKind.OPENING,
            statement_closing_balance=Decimal('800.00'),
        )

        result = self.service.verify(upload.pk, self.user.pk)

        self.assertEqual(result.status, STATUS_VERIFIED)
        self.assertEqual(result.app_balance, Decimal('800.00'))

    def test_exact_instant_is_used_without_day_end_guess(self) -> None:
        self._transaction(
            '200.00',
            datetime(2026, 4, 10, 15, 0, tzinfo=MOSCOW),
        )
        upload = self._upload(
            statement_balance_date=None,
            statement_balance_at=datetime(
                2026,
                4,
                10,
                12,
                0,
                tzinfo=MOSCOW,
            ),
            statement_closing_balance=Decimal('800.00'),
        )

        result = self.service.verify(upload.pk, self.user.pk)

        self.assertEqual(result.status, STATUS_VERIFIED)
        self.assertEqual(result.bank_balance_at, upload.statement_balance_at)

    def test_day_precision_movement_keeps_the_bank_day(self) -> None:
        self._later_income()
        self._transaction(
            '50.00',
            datetime(2026, 4, 10, 0, 0, tzinfo=UTC),
            transaction_type=TransactionType.EXPENSE,
        )
        upload = self._upload(
            statement_closing_balance=Decimal('800.00'),
        )

        result = self.service.verify(upload.pk, self.user.pk)

        self.assertEqual(result.status, STATUS_VERIFIED)

    def test_currencies_are_not_mixed_between_accounts(self) -> None:
        self._later_income()
        usd = Account.objects.create(
            user=self.user,
            name_account='USD',
            currency='USD',
            balance=Decimal('1000.00'),
        )
        self._transaction(
            '500.00',
            datetime(2026, 4, 11, 12, 0, tzinfo=UTC),
            account=usd,
        )
        upload = self._upload()

        result = self.service.verify(upload.pk, self.user.pk)

        self.assertEqual(result.status, STATUS_VERIFIED)
        self.assertEqual(result.app_balance, Decimal('800.00'))
        self.assertEqual(result.bank_balance, Decimal('800.00'))


class UnknownResultTests(StatementBalanceVerificationTestCase):
    def test_missing_balance_date_is_unknown(self) -> None:
        upload = self._upload(statement_balance_date=None)

        result = self.service.verify(upload.pk, self.user.pk)

        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertEqual(result.reason, REASON_NOT_CONFIGURED)
        self.assertFalse(result.blocks_final_reconciliation)

    def test_unknown_kind_is_reported(self) -> None:
        upload = self._upload(
            statement_balance_kind=BankStatementUpload.BalanceKind.UNKNOWN,
        )

        result = self.service.verify(upload.pk, self.user.pk)

        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertEqual(result.reason, REASON_KIND_UNKNOWN)

    def test_missing_timezone_is_not_inferred(self) -> None:
        upload = self._upload(statement_balance_timezone='')

        result = self.service.verify(upload.pk, self.user.pk)

        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertEqual(result.reason, REASON_DAY_TIMEZONE_UNKNOWN)
        self.assertIsNone(result.app_balance)

    def test_missing_bank_balance_is_unknown_not_zero(self) -> None:
        upload = self._upload(statement_closing_balance=None)

        result = self.service.verify(upload.pk, self.user.pk)

        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertEqual(result.reason, REASON_BANK_BALANCE_MISSING)
        self.assertIsNone(result.bank_balance)
        self.assertIsNone(result.difference)
        self.assertFalse(result.blocks_final_reconciliation)
        self.assertIsNone(
            self.service.final_reconciliation_block(
                user_id=self.user.pk,
                account_ids={self.account.pk},
            ),
        )

    def test_available_credit_needs_historical_limit_trust(self) -> None:
        credit = Account.objects.create(
            user=self.user,
            name_account='Кредитка',
            currency='RUB',
            balance=Decimal('1000.00'),
            type_account=constants.ACCOUNT_TYPE_CREDIT_CARD,
        )
        upload = self._upload(
            account=credit,
            statement_balance_kind=(BankStatementUpload.BalanceKind.AVAILABLE),
        )

        result = self.service.verify(upload.pk, self.user.pk)

        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertEqual(result.reason, REASON_AVAILABLE_CREDIT_UNKNOWN)

    def test_unresolved_influencing_row_blocks_conclusion(self) -> None:
        self._later_income()
        upload = self._upload()
        first = self.service.verify(upload.pk, self.user.pk)
        self.assertEqual(first.status, STATUS_VERIFIED)
        BankStatementRow.objects.create(
            upload=upload,
            transaction_date=datetime(2026, 4, 10, 0, 0, tzinfo=UTC),
            bank_calendar_date=BALANCE_DAY,
            date_precision=BankStatementRow.DatePrecision.DAY,
            decision=BankStatementRow.Decision.PENDING,
            source_row_position=1,
        )

        result = self.service.verify(upload.pk, self.user.pk)

        self.assertEqual(result.status, STATUS_STALE)
        self.assertEqual(result.last_result, STATUS_VERIFIED)
        self.assertEqual(result.reason, REASON_UNRESOLVED_ROWS)
        self.assertIsNone(result.difference)

    def test_unresolved_row_does_not_clear_a_retained_blocker(self) -> None:
        upload = self._upload(statement_closing_balance=Decimal('900.00'))
        mismatch = self.service.verify(upload.pk, self.user.pk)
        self.assertEqual(mismatch.status, STATUS_MISMATCH)
        BankStatementRow.objects.create(
            upload=upload,
            transaction_date=datetime(2026, 4, 10, 0, 0, tzinfo=UTC),
            bank_calendar_date=BALANCE_DAY,
            date_precision=BankStatementRow.DatePrecision.DAY,
            decision=BankStatementRow.Decision.DEFERRED,
            source_row_position=1,
        )

        result = self.service.verify(upload.pk, self.user.pk)

        self.assertEqual(result.reason, REASON_UNRESOLVED_ROWS)
        self.assertTrue(result.blocks_final_reconciliation)


class FinalReconciliationGuardTests(StatementBalanceVerificationTestCase):
    def test_mismatch_blocks_final_guard(self) -> None:
        upload = self._upload(statement_closing_balance=Decimal('900.00'))
        self.service.verify(upload.pk, self.user.pk)

        block = self.service.final_reconciliation_block(
            user_id=self.user.pk,
            account_ids={self.account.pk},
        )

        if block is None:
            self.fail('mismatch did not block')
        self.assertEqual(block.upload_ids, (upload.pk,))
        self.assertNotIn('900.00', ' '.join(block.reasons))

    def test_explanation_clears_blocker_and_writes_audit(self) -> None:
        upload = self._upload(statement_closing_balance=Decimal('900.00'))
        self.service.verify(upload.pk, self.user.pk)

        result = self.service.explain_mismatch(
            upload.pk,
            self.user.pk,
            reason='Банковская комиссия не проведена',
        )

        self.assertFalse(result.blocks_final_reconciliation)
        self.assertEqual(result.last_result, STATUS_MISMATCH)
        self.assertIsNone(
            self.service.final_reconciliation_block(
                user_id=self.user.pk,
                account_ids={self.account.pk},
            ),
        )
        upload.refresh_from_db()
        self.assertFalse(upload.balance_unexplained_mismatch)
        self.assertEqual(upload.balance_explained_by_id, self.user.pk)
        self.assertIsNotNone(upload.balance_explained_at)
        self.assertTrue(
            AuditLog.objects.filter(
                model_name='users.BankStatementUpload',
                object_pk=str(upload.pk),
                kind='statement_import_resolution',
            ).exists(),
        )

    def test_explanation_requires_a_reason(self) -> None:
        upload = self._upload(statement_closing_balance=Decimal('900.00'))
        self.service.verify(upload.pk, self.user.pk)

        with self.assertRaises(ValidationError):
            self.service.explain_mismatch(upload.pk, self.user.pk, reason='  ')

    def test_explanation_needs_an_unexplained_mismatch(self) -> None:
        upload = self._upload(
            statement_closing_balance=Decimal('1000.00'),
        )
        self.service.verify(upload.pk, self.user.pk)

        with self.assertRaises(ValidationError):
            self.service.explain_mismatch(
                upload.pk,
                self.user.pk,
                reason='Причина',
            )

    def test_new_mismatch_after_explanation_reopens_blocker(self) -> None:
        upload = self._upload(statement_closing_balance=Decimal('900.00'))
        self.service.verify(upload.pk, self.user.pk)
        self.service.explain_mismatch(
            upload.pk,
            self.user.pk,
            reason='Известная комиссия',
        )
        self._transaction(
            '50.00',
            datetime(2026, 4, 11, 12, 0, tzinfo=UTC),
        )

        result = self.service.verify(upload.pk, self.user.pk)

        self.assertTrue(result.blocks_final_reconciliation)

    def test_retention_keeps_blocker_but_hides_sums(self) -> None:
        upload = self._upload(statement_closing_balance=Decimal('900.00'))
        self.service.verify(upload.pk, self.user.pk)
        BankStatementUpload.objects.filter(pk=upload.pk).update(
            expires_at=timezone.now() - timedelta(days=1),
            retention_cleaned_at=timezone.now(),
            statement_closing_balance=None,
            account_balance_after=None,
            balance_discrepancy=None,
        )

        result = self.service.verification(upload.pk, self.user.pk)

        self.assertEqual(result.reason, REASON_DATA_CLEANED)
        self.assertIsNone(result.bank_balance)
        self.assertIsNone(result.difference)
        self.assertTrue(result.blocks_final_reconciliation)
        block = self.service.final_reconciliation_block(
            user_id=self.user.pk,
        )
        if block is None:
            self.fail('retention cleared the blocker')
        self.assertEqual(block.upload_ids, (upload.pk,))

    def test_guard_uses_retained_flag_even_when_status_unknown(self) -> None:
        upload = self._upload(statement_closing_balance=Decimal('900.00'))
        self.service.verify(upload.pk, self.user.pk)
        BankStatementUpload.objects.filter(pk=upload.pk).update(
            balance_verification_status=(
                BankStatementUpload.BalanceVerificationStatus.UNKNOWN
            ),
            balance_needs_recheck=True,
        )

        block = self.service.final_reconciliation_block(
            user_id=self.user.pk,
            account_ids={self.account.pk},
        )

        if block is None:
            self.fail('retained flag was ignored because of the last result')
        self.assertEqual(block.upload_ids, (upload.pk,))

    def test_guard_does_not_leak_to_another_user(self) -> None:
        upload = self._upload(statement_closing_balance=Decimal('900.00'))
        self.service.verify(upload.pk, self.user.pk)
        other = cast('User', UserFactory())

        self.assertIsNone(
            self.service.final_reconciliation_block(user_id=other.pk),
        )
        with self.assertRaises(BankStatementUpload.DoesNotExist):
            self.service.verification(upload.pk, other.pk)


class StalenessTests(StatementBalanceVerificationTestCase):
    def test_influencing_change_after_moment_marks_stale(self) -> None:
        self._later_income()
        upload = self._upload()
        self.service.verify(upload.pk, self.user.pk)

        changed = mark_balance_checks_stale(
            {self.account.pk},
            [datetime(2026, 4, 11, 12, 0, tzinfo=UTC)],
        )

        self.assertEqual(changed, 1)
        upload.refresh_from_db()
        self.assertTrue(upload.balance_needs_recheck)
        result = self.service.verification(upload.pk, self.user.pk)
        self.assertEqual(result.status, STATUS_STALE)
        self.assertEqual(result.reason, REASON_MOVEMENT_CHANGED)
        self.assertEqual(result.last_result, STATUS_VERIFIED)

    def test_change_before_moment_does_not_mark_stale(self) -> None:
        self._later_income()
        upload = self._upload()
        self.service.verify(upload.pk, self.user.pk)

        changed = mark_balance_checks_stale(
            {self.account.pk},
            [datetime(2026, 4, 9, 12, 0, tzinfo=UTC)],
        )

        self.assertEqual(changed, 0)
        upload.refresh_from_db()
        self.assertFalse(upload.balance_needs_recheck)

    def test_category_only_edit_does_not_invalidate_in_service(
        self,
    ) -> None:
        upload = self._upload()
        self.service.verify(upload.pk, self.user.pk)
        self._later_income()
        self.service.verify(upload.pk, self.user.pk)
        transaction = Transaction.objects.latest('pk')
        other_category = Category.objects.create(
            user=self.user,
            name='Другая',
            type=TransactionType.INCOME,
        )
        service = ApplicationContainer().transactions.transaction_service()

        service.update_transaction(
            UpdateTransactionCommand(
                user=self.user,
                transaction_obj=transaction,
                account=self.account,
                category=other_category,
                amount=transaction.amount,
                transaction_date=transaction.date,
                type_value=transaction.type,
            ),
        )

        upload.refresh_from_db()
        self.assertFalse(upload.balance_needs_recheck)

    def test_money_edit_after_moment_marks_stale(self) -> None:
        upload = self._upload()
        self.service.verify(upload.pk, self.user.pk)
        self._later_income()
        self.service.verify(upload.pk, self.user.pk)
        transaction = Transaction.objects.latest('pk')
        service = ApplicationContainer().transactions.transaction_service()

        service.update_transaction(
            UpdateTransactionCommand(
                user=self.user,
                transaction_obj=transaction,
                account=self.account,
                category=transaction.category,
                amount=Decimal('250.00'),
                transaction_date=transaction.date,
                type_value=transaction.type,
            ),
        )

        upload.refresh_from_db()
        self.assertTrue(upload.balance_needs_recheck)
        self.assertEqual(upload.balance_stale_reason, REASON_MOVEMENT_CHANGED)

    def test_money_delete_after_moment_marks_stale(self) -> None:
        upload = self._upload()
        self.service.verify(upload.pk, self.user.pk)
        transaction = self._later_income()
        self.service.verify(upload.pk, self.user.pk)
        service = ApplicationContainer().transactions.transaction_service()

        service.delete_transaction(user=self.user, transaction_obj=transaction)

        upload.refresh_from_db()
        self.assertTrue(upload.balance_needs_recheck)


class MarkupClosingCheckTests(StatementBalanceVerificationTestCase):
    def test_finalize_runs_the_historical_check_not_current_balance(
        self,
    ) -> None:
        calls: list[tuple[int, int]] = []

        class _Recorder:
            def verify(self, upload_id: int, user_id: int) -> None:
                calls.append((upload_id, user_id))

        upload = self._upload()
        service = StatementMarkupService(
            balance_service=BalanceService(),
            account_repository=AccountRepository(),
            transfer_log_repository=TransferMoneyLogRepository(),
            statement_row_repository=StatementRowRepository(),
            coverage_service=(
                ApplicationContainer().finance_account.account_coverage_service()
            ),
            balance_verification=_Recorder(),  # type: ignore[arg-type]
        )

        service._finalize(upload)

        self.assertEqual(calls, [(upload.pk, self.user.pk)])


class ReconciliationViewBalanceTests(StatementBalanceVerificationTestCase):
    def _url(self, upload: BankStatementUpload) -> str:
        return reverse(
            'finance_account:bank_statement_reconciliation',
            args=[upload.pk],
        )

    def test_owner_confirms_and_verifies_balance(self) -> None:
        upload = self._upload(statement_closing_balance=Decimal('1000.00'))
        self.client.force_login(self.user)

        response = self.client.post(
            self._url(upload),
            {
                'action': 'confirm_balance',
                'balance_date': '2026-04-10',
                'balance_kind': BankStatementUpload.BalanceKind.CLOSING,
                'timezone_name': 'Europe/Moscow',
            },
        )

        self.assertEqual(response.status_code, 302)
        upload.refresh_from_db()
        self.assertEqual(upload.statement_balance_date, BALANCE_DAY)
        self.assertEqual(
            upload.statement_balance_kind,
            BankStatementUpload.BalanceKind.CLOSING,
        )
        self.assertEqual(upload.balance_verification_status, 'verified')
        self.assertFalse(upload.balance_unexplained_mismatch)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_other_user_cannot_confirm_balance(self) -> None:
        upload = self._upload(
            statement_balance_date=None,
            statement_balance_kind=BankStatementUpload.BalanceKind.UNKNOWN,
            statement_balance_timezone='',
        )
        other = cast('User', UserFactory())
        self.client.force_login(other)

        response = self.client.post(
            self._url(upload),
            {
                'action': 'confirm_balance',
                'balance_date': '2026-04-10',
                'balance_kind': BankStatementUpload.BalanceKind.CLOSING,
                'timezone_name': 'Europe/Moscow',
            },
        )

        self.assertEqual(response.status_code, 404)
        upload.refresh_from_db()
        self.assertIsNone(upload.statement_balance_date)
