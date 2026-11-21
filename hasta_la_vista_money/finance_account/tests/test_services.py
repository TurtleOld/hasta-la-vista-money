"""Tests for finance account services."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, cast
from unittest import mock

from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.factories import (
    AccountFactory,
    TransferMoneyLogFactory,
)
from hasta_la_vista_money.finance_account.models import (
    Account,
    StatementPeriodCoverage,
    TransferMoneyLog,
)
from hasta_la_vista_money.finance_account.services.balance_service import (
    BalanceService,
)
from hasta_la_vista_money.system.models import AuditLog
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.factories import UserFactory
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    FamilyGroupMembership,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User as UserType
else:
    from django.contrib.auth import get_user_model

    UserType = get_user_model()


class TestAccountServices(TestCase):
    """Test cases for account service functions."""

    def setUp(self) -> None:
        self.user1: UserType = cast('UserType', UserFactory())
        self.user2: UserType = cast('UserType', UserFactory())
        self.container = ApplicationContainer()
        self.account_service = self.container.finance_account.account_service()

        self.account1: Account = cast(
            'Account',
            AccountFactory(user=self.user1, balance=Decimal('1000.00')),
        )
        self.account2: Account = cast(
            'Account',
            AccountFactory(user=self.user1, balance=Decimal('500.00')),
        )
        self.account3: Account = cast(
            'Account',
            AccountFactory(user=self.user2, balance=Decimal('2000.00')),
        )

    def test_get_accounts_for_user_or_group_none(self) -> None:
        """Test get_accounts_for_user_or_group with None group_id."""
        accounts = self.account_service.get_accounts_for_user_or_group(
            self.user1,
            None,
        )

        self.assertEqual(accounts.count(), 2)
        self.assertIn(self.account1, accounts)
        self.assertIn(self.account2, accounts)
        self.assertNotIn(self.account3, accounts)

    def test_balance_change_ignores_stale_account_value(self) -> None:
        stale_account = Account.objects.get(pk=self.account1.pk)
        Account.objects.filter(pk=self.account1.pk).update(
            balance=Decimal('1250.00'),
        )

        BalanceService().apply_receipt_spend(
            stale_account,
            Decimal('100.00'),
        )

        self.account1.refresh_from_db()
        self.assertEqual(self.account1.balance, Decimal('1150.00'))

    def test_get_accounts_for_user_or_group_my(self) -> None:
        """Test get_accounts_for_user_or_group with 'my' group_id."""
        accounts = self.account_service.get_accounts_for_user_or_group(
            self.user1,
            'my',
        )

        self.assertEqual(accounts.count(), 2)
        self.assertIn(self.account1, accounts)
        self.assertIn(self.account2, accounts)
        self.assertNotIn(self.account3, accounts)

    def test_get_accounts_for_user_or_group_with_group(self) -> None:
        """Owner can see all accounts for an owned family group."""
        group = Group.objects.create(name='Test Group')
        self.user1.groups.add(group)
        self.user2.groups.add(group)
        FamilyGroupMembership.objects.create(
            group=group,
            user=self.user1,
            role=FamilyGroupMembership.Role.OWNER,
        )
        FamilyGroupMembership.objects.create(
            group=group,
            user=self.user2,
            role=FamilyGroupMembership.Role.VIEWER,
        )

        accounts = self.account_service.get_accounts_for_user_or_group(
            self.user1,
            str(group.pk),
        )

        self.assertEqual(accounts.count(), 3)
        self.assertIn(self.account1, accounts)
        self.assertIn(self.account2, accounts)
        self.assertIn(self.account3, accounts)

    def test_get_accounts_for_user_or_group_viewer_group(self) -> None:
        """Viewer reads accounts of all group members."""
        group = Group.objects.create(name='Viewer Group')
        self.user1.groups.add(group)
        self.user2.groups.add(group)
        FamilyGroupMembership.objects.create(
            group=group,
            user=self.user1,
            role=FamilyGroupMembership.Role.OWNER,
        )
        FamilyGroupMembership.objects.create(
            group=group,
            user=self.user2,
            role=FamilyGroupMembership.Role.VIEWER,
        )

        accounts = self.account_service.get_accounts_for_user_or_group(
            self.user2,
            str(group.pk),
        )

        self.assertEqual(accounts.count(), 3)
        self.assertIn(self.account1, accounts)
        self.assertIn(self.account2, accounts)
        self.assertIn(self.account3, accounts)

    def test_get_accounts_for_user_or_group_invalid_group(self) -> None:
        """Test get_accounts_for_user_or_group with invalid group_id."""
        accounts = self.account_service.get_accounts_for_user_or_group(
            self.user1,
            '999',
        )

        # Unknown or inaccessible groups should not leak user's own accounts.
        self.assertEqual(accounts.count(), 0)
        self.assertNotIn(self.account1, accounts)
        self.assertNotIn(self.account2, accounts)

    def test_get_balances_by_currency(self) -> None:
        """Test account balances grouped by currency."""
        accounts = Account.objects.filter(user=self.user1)
        result = self.account_service.get_balances_by_currency(accounts)
        self.assertEqual(result, {'RUB': Decimal('1500.00')})

    def test_get_balances_by_currency_empty_queryset(self) -> None:
        """Test currency balances with an empty queryset."""
        accounts = Account.objects.none()
        result = self.account_service.get_balances_by_currency(accounts)
        self.assertEqual(result, {})

    def test_get_balances_by_currency_single_account(self) -> None:
        """Test currency balances with a single account."""
        accounts = Account.objects.filter(pk=self.account1.pk)
        result = self.account_service.get_balances_by_currency(accounts)
        self.assertEqual(result, {'RUB': Decimal('1000.00')})

    def test_get_balances_by_currency_parametrized(self) -> None:
        """Test parametrized sum calculation with different account sets.

        Tests boundary conditions, precision, and currency handling.
        """
        testcases = [
            {
                'balances': [Decimal('1000.00'), Decimal('500.00')],
                'expected': Decimal('1500.00'),
            },
            {'balances': [Decimal('123.45')], 'expected': Decimal('123.45')},
            {'balances': [], 'expected': Decimal('0.00')},
            {
                'balances': [Decimal('0.1'), Decimal('0.2')],
                'expected': Decimal('0.3'),
            },
            {
                'balances': [Decimal('1000000000.00'), Decimal('0.01')],
                'expected': Decimal('1000000000.01'),
            },
        ]
        for case in testcases:
            with self.subTest(balances=case['balances']):
                balances_list: list[Decimal] = cast(
                    'list[Decimal]',
                    case['balances'],
                )
                accounts_list: list[Account] = [
                    cast(
                        'Account',
                        AccountFactory(
                            user=self.user1,
                            balance=bal,
                            currency='RUB',
                        ),
                    )
                    for bal in balances_list
                ]
                qs = Account.objects.filter(
                    pk__in=[acc.pk for acc in accounts_list],
                )
                result = self.account_service.get_balances_by_currency(qs)
                expected = {'RUB': case['expected']} if balances_list else {}
                self.assertEqual(result, expected)

        acc1 = cast(
            'Account',
            AccountFactory(
                user=self.user1,
                balance=Decimal('100.00'),
                currency='RUB',
            ),
        )
        acc2 = cast(
            'Account',
            AccountFactory(
                user=self.user1,
                balance=Decimal('200.00'),
                currency='USD',
            ),
        )
        qs = Account.objects.filter(pk__in=[acc1.pk, acc2.pk])
        result = self.account_service.get_balances_by_currency(qs)
        self.assertEqual(
            result,
            {'RUB': Decimal('100.00'), 'USD': Decimal('200.00')},
        )

    def test_get_transfer_money_log(self) -> None:
        """Test get_transfer_money_log function."""
        TransferMoneyLogFactory(
            user=self.user1,
            from_account=self.account1,
            to_account=self.account2,
            amount=Decimal('100.00'),
        )
        TransferMoneyLogFactory(
            user=self.user1,
            from_account=self.account2,
            to_account=self.account1,
            amount=Decimal('200.00'),
        )
        TransferMoneyLogFactory(
            user=self.user2,
            from_account=self.account3,
            to_account=self.account1,
            amount=Decimal('300.00'),
        )

        logs = self.account_service.get_transfer_money_log(self.user1)

        self.assertEqual(logs.count(), 2)
        self.assertTrue(all(log.user == self.user1 for log in logs))

    def test_get_transfer_money_log_empty(self) -> None:
        """Test get_transfer_money_log with no transfers."""
        logs = self.account_service.get_transfer_money_log(self.user1)
        self.assertEqual(logs.count(), 0)

    def test_get_transfer_money_log_limit(self) -> None:
        """Test get_transfer_money_log with more than 10 transfers."""
        for _ in range(15):
            TransferMoneyLogFactory(
                user=self.user1,
                from_account=self.account1,
                to_account=self.account2,
                amount=Decimal('10.00'),
            )

        logs = self.account_service.get_transfer_money_log(self.user1)
        self.assertLessEqual(logs.count(), 10)

    def _upload(
        self,
        *,
        total_transactions: int = 0,
        account: Account | None = None,
    ) -> BankStatementUpload:
        return BankStatementUpload.objects.create(
            user=self.user1,
            account=account or self.account1,
            pdf_file='bank_statements/control.pdf',
            total_transactions=total_transactions,
        )

    def _row(
        self,
        upload: BankStatementUpload,
        position: int,
        *,
        decision: str = BankStatementRow.Decision.PENDING,
        exclusion_code: str = '',
        transaction_date: datetime | None = None,
        kind: str = '',
    ) -> BankStatementRow:
        return BankStatementRow.objects.create(
            upload=upload,
            transaction_type=BankStatementRow.TransactionType.EXPENSE,
            transaction_date=transaction_date
            or datetime(
                2026,
                3,
                10,
                tzinfo=timezone.get_current_timezone(),
            ),
            amount=Decimal('100.00'),
            description='Покупка',
            source_ref=f'control-{position}',
            source_row_position=position,
            decision=decision,
            exclusion_code=exclusion_code,
            kind=kind,
        )

    def test_explicit_statement_period_records_coverage(self) -> None:
        upload = self._upload()
        service = self.container.users.statement_coverage_service()

        coverage = service.record_statement_period(
            upload,
            date(2026, 3, 1),
            date(2026, 3, 31),
        )
        summary = service.summary(
            self.account1,
            date(2026, 3, 1),
            date(2026, 3, 31),
        )

        if coverage is None:
            self.fail('statement period was not recorded')
        self.assertEqual(
            coverage.source,
            StatementPeriodCoverage.Source.BANK_STATEMENT,
        )
        self.assertEqual(coverage.author, self.user1)
        self.assertEqual(coverage.upload, upload)
        self.assertEqual(summary.state, 'covered')
        self.assertEqual(len(summary.intervals), 1)
        self.assertEqual(
            summary.intervals[0].source_label,
            'Период банковской выписки',
        )
        self.assertEqual(summary.gaps, ())

    def test_coverage_is_not_derived_from_row_dates(self) -> None:
        upload = self._upload(total_transactions=1)
        self._row(upload, 1)
        service = self.container.users.statement_coverage_service()

        summary = service.summary(
            self.account1,
            date(2026, 3, 1),
            date(2026, 3, 31),
        )

        self.assertEqual(summary.state, 'unknown')
        self.assertEqual(summary.intervals, ())
        self.assertFalse(
            StatementPeriodCoverage.objects.filter(
                account=self.account1,
            ).exists(),
        )

    def test_manual_coverage_marks_cash_period_and_requires_owner(self) -> None:
        cash: Account = cast(
            'Account',
            AccountFactory(
                user=self.user1,
                type_account=constants.ACCOUNT_TYPE_CASH,
            ),
        )
        service = self.container.users.statement_coverage_service()

        coverage = service.confirm_manual(
            self.user1,
            cash,
            date(2026, 1, 1),
            date(2026, 1, 31),
        )

        self.assertEqual(
            coverage.source,
            StatementPeriodCoverage.Source.MANUAL_CONFIRMATION,
        )
        self.assertEqual(
            service.summary(cash, date(2026, 1, 1), date(2026, 1, 31)).state,
            'covered',
        )
        repeated = service.confirm_manual(
            self.user1,
            cash,
            date(2026, 1, 1),
            date(2026, 1, 31),
        )
        self.assertEqual(repeated.pk, coverage.pk)
        self.assertEqual(
            StatementPeriodCoverage.objects.filter(account=cash).count(),
            1,
        )
        with self.assertRaises(PermissionDenied):
            service.confirm_manual(
                self.user2,
                cash,
                date(2026, 2, 1),
                date(2026, 2, 28),
            )

    def test_manual_cash_coverage_does_not_close_row_problems(self) -> None:
        cash: Account = cast(
            'Account',
            AccountFactory(
                user=self.user1,
                type_account=constants.ACCOUNT_TYPE_CASH,
            ),
        )
        upload = self._upload(account=cash)
        self._row(
            upload,
            1,
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
            transaction_date=timezone.now(),
        )
        start = timezone.localdate().replace(day=1)
        end = timezone.localdate()
        coverage_service = self.container.users.statement_coverage_service()
        coverage_service.confirm_manual(self.user1, cash, start, end)

        control = self.container.users.accounting_control_service().build(
            cash,
            start,
            end,
        )

        self.assertEqual(control.coverage.state, 'covered')
        self.assertEqual(control.rows.awaiting_markup, 1)
        self.assertFalse(control.balance.checked)

    def test_coverage_distinguishes_unknown_partial_and_empty(self) -> None:
        service = self.container.users.statement_coverage_service()
        period = (date(2026, 5, 1), date(2026, 5, 20))

        unknown = service.summary(self.account1, *period)
        empty_upload = self._upload(total_transactions=0)
        service.record_statement_period(
            empty_upload,
            date(2026, 5, 1),
            date(2026, 5, 20),
        )
        empty = service.summary(self.account1, *period)
        service.confirm_manual(
            self.user1,
            self.account1,
            date(2026, 5, 24),
            date(2026, 5, 25),
        )
        partial = service.summary(
            self.account1,
            date(2026, 5, 1),
            date(2026, 5, 25),
        )

        self.assertEqual(unknown.state, 'unknown')
        self.assertEqual(empty.state, 'covered')
        self.assertTrue(empty.intervals[0].has_no_rows)
        self.assertEqual(partial.state, 'partial')
        self.assertEqual(len(partial.gaps), 1)
        self.assertEqual(partial.gaps[0].period_start, date(2026, 5, 21))
        self.assertEqual(partial.gaps[0].period_end, date(2026, 5, 23))

    def test_control_includes_unknown_period_upload_by_historical_rows(
        self,
    ) -> None:
        upload = self._upload(total_transactions=2)
        self._row(
            upload,
            1,
            transaction_date=datetime(
                2026,
                1,
                10,
                tzinfo=timezone.get_current_timezone(),
            ),
        )
        unknown_date = self._row(upload, 2)
        BankStatementRow.objects.filter(pk=unknown_date.pk).update(
            transaction_date=None,
        )

        control = self.container.users.accounting_control_service().build(
            self.account1,
            date(2026, 1, 1),
            date(2026, 1, 31),
        )

        self.assertEqual(len(control.uploads), 1)
        self.assertEqual(control.rows.pending, 2)
        self.assertEqual(control.coverage.state, 'unknown')

    def test_control_excludes_empty_unknown_period_upload(self) -> None:
        self._upload()

        control = self.container.users.accounting_control_service().build(
            self.account1,
            date(2026, 1, 1),
            date(2026, 1, 31),
        )

        self.assertEqual(control.uploads, ())

    def test_coverage_gaps_handle_maximum_date(self) -> None:
        service = self.container.users.statement_coverage_service()
        service.confirm_manual(
            self.user1,
            self.account1,
            date(9999, 12, 1),
            date(9999, 12, 31),
        )

        summary = service.summary(
            self.account1,
            date(9999, 12, 1),
            date(9999, 12, 31),
        )

        self.assertEqual(summary.state, 'covered')
        self.assertEqual(summary.gaps, ())

    def test_control_scopes_row_problems_to_the_selected_period(self) -> None:
        upload = self._upload(total_transactions=2)
        coverage_service = self.container.users.statement_coverage_service()
        coverage_service.record_statement_period(
            upload,
            date(2026, 1, 1),
            date(2026, 1, 31),
        )
        self._row(
            upload,
            1,
            transaction_date=datetime(
                2026,
                1,
                5,
                tzinfo=timezone.get_current_timezone(),
            ),
        )
        self._row(
            upload,
            2,
            transaction_date=datetime(
                2026,
                2,
                5,
                tzinfo=timezone.get_current_timezone(),
            ),
        )

        control = self.container.users.accounting_control_service().build(
            self.account1,
            date(2026, 1, 1),
            date(2026, 1, 31),
        )

        self.assertEqual(control.rows.pending, 1)

    def test_control_keeps_rows_exclusions_and_balance_separate(self) -> None:
        upload = self._upload(total_transactions=2)
        coverage_service = self.container.users.statement_coverage_service()
        coverage_service.record_statement_period(
            upload,
            date(2026, 3, 1),
            date(2026, 3, 31),
        )
        self._row(upload, 1)
        self._row(
            upload,
            2,
            decision=BankStatementRow.Decision.SKIPPED,
            exclusion_code=BankStatementRow.ExclusionCode.NON_FINANCIAL_BANK_RECORD,
        )
        self._row(
            upload,
            3,
            decision=BankStatementRow.Decision.SKIPPED,
        )
        self._row(
            upload,
            4,
            decision=BankStatementRow.Decision.EXPIRED,
        )
        control_service = self.container.users.accounting_control_service()

        control = control_service.build(
            self.account1,
            date(2026, 3, 1),
            date(2026, 3, 31),
        )

        self.assertEqual(control.coverage.state, 'covered')
        self.assertEqual(control.rows.pending, 1)
        self.assertEqual(control.rows.legacy_skips, 1)
        self.assertEqual(control.rows.expired, 1)
        self.assertEqual(len(control.exclusions), 1)
        self.assertFalse(control.balance.checked)
        self.assertEqual(control.balance.label, 'Не проверено')

    def test_control_does_not_treat_availability_or_adapter_as_coverage(
        self,
    ) -> None:
        upload = self._upload()
        service = self.container.users.accounting_control_service()
        start = timezone.localdate().replace(day=1)
        end = timezone.localdate()

        control = service.build(self.account1, start, end)

        if not control.uploads:
            self.fail('upload is missing from the control period')
        self.assertTrue(control.uploads[0].data_available)
        self.assertFalse(control.uploads[0].has_markup_rows)
        self.assertIn('Не покрыт', control.uploads[0].markup_label)
        self.assertEqual(control.coverage.state, 'unknown')

        self._row(
            upload,
            1,
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
            kind='card',
        )
        control = service.build(self.account1, start, end)

        self.assertTrue(control.uploads[0].has_markup_rows)
        self.assertEqual(control.coverage.state, 'unknown')

    def _balance_upload(
        self,
        *,
        closing: Decimal,
        moment: datetime,
        account: Account | None = None,
    ) -> BankStatementUpload:
        upload = self._upload(account=account, total_transactions=1)
        upload.statement_closing_balance = closing
        upload.balance_moment = moment
        upload.save(
            update_fields=['statement_closing_balance', 'balance_moment'],
        )
        self.container.users.statement_coverage_service().record_statement_period(
            upload,
            moment.date(),
            moment.date(),
        )
        return upload

    def test_statement_balance_uses_history_at_same_moment_and_currency(
        self,
    ) -> None:
        moment = timezone.now() - timedelta(days=2)
        income = Category.objects.create(
            user=self.user1,
            name='Доход',
            type=TransactionType.INCOME,
        )
        Transaction.objects.create(
            user=self.user1,
            account=self.account1,
            category=income,
            type=TransactionType.INCOME,
            amount=Decimal('200.00'),
            date=moment + timedelta(days=1),
        )
        upload = self._balance_upload(
            closing=Decimal('800.00'),
            moment=moment,
        )
        service = self.container.users.statement_balance_verification_service()

        service.verify(upload)

        upload.refresh_from_db()
        self.assertEqual(
            upload.balance_result,
            BankStatementUpload.BalanceResult.MATCHED,
        )
        self.assertTrue(upload.balance_is_actual)
        self.assertEqual(upload.balance_currency, 'RUB')
        self.assertEqual(upload.account_balance_after, Decimal('800.00'))
        self.assertEqual(upload.balance_discrepancy, Decimal('0.00'))
        self.assertIsNotNone(upload.balance_checked_at)

        control = self.container.users.accounting_control_service().build(
            self.account1,
            moment.date(),
            moment.date(),
        )
        self.assertTrue(control.balance.checked)
        self.assertTrue(control.balance.actual)
        self.assertEqual(
            control.balance.result,
            BankStatementUpload.BalanceResult.MATCHED,
        )
        self.assertFalse(control.balance.blocks_final_reconciliation)

    def test_missing_balance_data_is_not_checked_not_zero(self) -> None:
        upload = self._upload(total_transactions=1)
        service = self.container.users.statement_balance_verification_service()

        service.verify(upload)

        upload.refresh_from_db()
        self.assertEqual(
            upload.balance_result,
            BankStatementUpload.BalanceResult.NOT_CHECKED,
        )
        self.assertEqual(
            upload.balance_reason,
            BankStatementUpload.BalanceReason.MISSING_BALANCE,
        )
        self.assertIsNone(upload.account_balance_after)
        self.assertIsNone(upload.balance_discrepancy)
        control = self.container.users.accounting_control_service().build(
            self.account1,
            timezone.localdate().replace(day=1),
            timezone.localdate(),
        )
        self.assertFalse(control.balance.checked)
        self.assertIsNone(control.balance.bank_balance)
        self.assertIsNone(control.balance.ledger_balance)
        self.assertEqual(control.balance.label, 'Не проверено')

    def test_missing_moment_or_currency_is_not_substituted(self) -> None:
        service = self.container.users.statement_balance_verification_service()
        missing_moment = self._upload(total_transactions=1)
        missing_moment.statement_closing_balance = Decimal('100.00')
        missing_moment.save(update_fields=['statement_closing_balance'])

        service.verify(missing_moment)

        missing_moment.refresh_from_db()
        self.assertEqual(
            missing_moment.balance_result,
            BankStatementUpload.BalanceResult.NOT_CHECKED,
        )
        self.assertEqual(
            missing_moment.balance_reason,
            BankStatementUpload.BalanceReason.MISSING_MOMENT,
        )
        self.assertIsNone(missing_moment.account_balance_after)

        Account.objects.filter(pk=self.account1.pk).update(currency='')
        self.account1.refresh_from_db()
        missing_currency = self._balance_upload(
            closing=Decimal('1000.00'),
            moment=timezone.now(),
        )

        service.verify(missing_currency)

        missing_currency.refresh_from_db()
        self.assertEqual(
            missing_currency.balance_result,
            BankStatementUpload.BalanceResult.NOT_CHECKED,
        )
        self.assertEqual(
            missing_currency.balance_reason,
            BankStatementUpload.BalanceReason.MISSING_CURRENCY,
        )
        self.assertIsNone(missing_currency.account_balance_after)
        self.assertIsNone(missing_currency.balance_discrepancy)

    def test_amount_or_date_change_invalidates_and_category_does_not(
        self,
    ) -> None:
        moment = timezone.now() - timedelta(days=2)
        expense = Category.objects.create(
            user=self.user1,
            name='Расход',
            type=TransactionType.EXPENSE,
        )
        other_expense = Category.objects.create(
            user=self.user1,
            name='Другой расход',
            type=TransactionType.EXPENSE,
        )
        transaction = Transaction.objects.create(
            user=self.user1,
            account=self.account1,
            category=expense,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=moment - timedelta(days=1),
        )
        Account.objects.filter(pk=self.account1.pk).update(
            balance=Decimal('900.00'),
        )
        upload = self._balance_upload(
            closing=Decimal('900.00'),
            moment=moment,
        )
        service = self.container.users.statement_balance_verification_service()
        control_service = self.container.users.accounting_control_service()
        service.verify(upload)

        transaction.category = other_expense
        transaction.save(update_fields=['category'])
        control = control_service.build(
            self.account1,
            moment.date(),
            moment.date(),
        )
        self.assertTrue(control.balance.actual)
        self.assertEqual(
            control.balance.result,
            BankStatementUpload.BalanceResult.MATCHED,
        )

        transaction.amount = Decimal('200.00')
        transaction.save(update_fields=['amount'])
        Account.objects.filter(pk=self.account1.pk).update(
            balance=Decimal('800.00'),
        )
        control = control_service.build(
            self.account1,
            moment.date(),
            moment.date(),
        )
        self.assertFalse(control.balance.actual)
        self.assertEqual(
            control.balance.reason,
            BankStatementUpload.BalanceReason.MONEY_OR_DATE_CHANGED,
        )

        service.verify(upload)
        upload.refresh_from_db()
        self.assertEqual(
            upload.balance_result,
            BankStatementUpload.BalanceResult.DISCREPANCY,
        )
        transaction.date = moment + timedelta(days=1)
        transaction.save(update_fields=['date'])
        control = control_service.build(
            self.account1,
            moment.date(),
            moment.date(),
        )
        self.assertFalse(control.balance.actual)

    def test_retention_keeps_balance_metadata_without_sums(self) -> None:
        moment = timezone.now() - timedelta(days=2)
        upload = self._balance_upload(
            closing=Decimal('900.00'),
            moment=moment,
        )
        service = self.container.users.statement_balance_verification_service()
        service.verify(upload)
        service.explain(
            upload,
            self.user1,
            BankStatementUpload.ExplanationCode.BANK_POSTING_DATE_DIFFERENCE,
        )
        upload.refresh_from_db()
        checked_at = upload.balance_checked_at
        upload.expires_at = timezone.now() - timedelta(minutes=1)
        upload.save(update_fields=['expires_at'])

        self.container.users.bank_statement_retention_service().cleanup_expired()

        upload.refresh_from_db()
        self.assertIsNone(upload.statement_closing_balance)
        self.assertIsNone(upload.account_balance_after)
        self.assertIsNone(upload.balance_discrepancy)
        self.assertEqual(upload.balance_moment, moment)
        self.assertEqual(
            upload.balance_type,
            BankStatementUpload.BalanceType.CLOSING,
        )
        self.assertEqual(
            upload.balance_result,
            BankStatementUpload.BalanceResult.DISCREPANCY,
        )
        self.assertEqual(upload.balance_checked_at, checked_at)
        self.assertFalse(upload.balance_is_actual)
        self.assertEqual(
            upload.balance_reason,
            BankStatementUpload.BalanceReason.BANK_DATA_CLEANED,
        )
        self.assertEqual(
            upload.balance_explanation_code,
            BankStatementUpload.ExplanationCode.BANK_POSTING_DATE_DIFFERENCE,
        )
        self.assertEqual(upload.balance_explained_by, self.user1)

    def test_approved_explanations_are_audited_and_never_apply_money(
        self,
    ) -> None:
        categories = {
            code: ('complete' if code.endswith('DIFFERENCE') else 'incomplete')
            for code in BankStatementUpload.ExplanationCode.values
        }
        for code, completeness in categories.items():
            with self.subTest(code=code):
                account: Account = cast(
                    'Account',
                    AccountFactory(
                        user=self.user1,
                        balance=Decimal('1000.00'),
                    ),
                )
                upload = self._balance_upload(
                    closing=Decimal('900.00'),
                    moment=timezone.now() - timedelta(days=2),
                    account=account,
                )
                users = self.container.users
                service = users.statement_balance_verification_service()
                service.verify(upload)
                upload.refresh_from_db()
                discrepancy = upload.balance_discrepancy
                account_balance = account.balance
                transactions = Transaction.objects.count()
                if upload.balance_moment is None:
                    self.fail('the fixture must store a balance moment')
                moment = upload.balance_moment
                control_service = (
                    self.container.users.accounting_control_service()
                )
                unexplained = control_service.build(
                    account,
                    moment.date(),
                    moment.date(),
                )
                self.assertTrue(unexplained.balance.blocks_final_reconciliation)

                service.explain(upload, self.user1, code)

                upload.refresh_from_db()
                self.assertEqual(upload.balance_explanation_code, code)
                self.assertEqual(upload.balance_explained_by, self.user1)
                self.assertIsNotNone(upload.balance_explained_at)
                self.assertEqual(upload.balance_discrepancy, discrepancy)
                self.assertEqual(
                    upload.balance_result,
                    BankStatementUpload.BalanceResult.DISCREPANCY,
                )
                account.refresh_from_db()
                self.assertEqual(account.balance, account_balance)
                self.assertEqual(Transaction.objects.count(), transactions)
                audit = AuditLog.objects.filter(
                    user=self.user1,
                    object_pk=str(upload.pk),
                ).latest('pk')
                self.assertEqual(
                    audit.diff['explanation_code'],
                    code,
                )
                self.assertEqual(
                    audit.diff['completeness'],
                    completeness,
                )
                control = control_service.build(
                    account,
                    moment.date(),
                    moment.date(),
                )
                self.assertFalse(
                    control.balance.blocks_final_reconciliation,
                )
                self.assertEqual(
                    control.balance.explanation_completeness,
                    completeness,
                )

    def test_explanation_rejects_free_text_structural_errors_and_other_users(
        self,
    ) -> None:
        service = self.container.users.statement_balance_verification_service()
        upload = self._balance_upload(
            closing=Decimal('900.00'),
            moment=timezone.now() - timedelta(days=2),
        )
        service.verify(upload)

        with self.assertRaises(ValidationError):
            service.explain(upload, self.user1, 'произвольный текст')
        with self.assertRaises(PermissionDenied):
            service.explain(
                upload,
                self.user2,
                BankStatementUpload.ExplanationCode.CONSCIOUS_INCOMPLETE_ACCOUNTING,
            )
        upload.refresh_from_db()
        self.assertEqual(upload.balance_explanation_code, '')

        structural = self._balance_upload(
            closing=Decimal('900.00'),
            moment=timezone.now() - timedelta(days=1),
        )
        structural.status = BankStatementUpload.Status.FAILED
        structural.error_message = 'Сломанная структура файла'
        structural.save(update_fields=['status', 'error_message'])
        service.verify(structural)
        with self.assertRaises(ValidationError):
            service.explain(
                structural,
                self.user1,
                BankStatementUpload.ExplanationCode.BANK_POSTING_DATE_DIFFERENCE,
            )

        matched = self._balance_upload(
            closing=Decimal('1000.00'),
            moment=timezone.now() - timedelta(days=1),
        )
        service.verify(matched)
        matched.refresh_from_db()
        if matched.balance_result != BankStatementUpload.BalanceResult.MATCHED:
            self.fail('the fixture must produce a matched balance')
        with self.assertRaises(ValidationError):
            service.explain(
                matched,
                self.user1,
                BankStatementUpload.ExplanationCode.BANK_POSTING_DATE_DIFFERENCE,
            )


class TestTransferService(TestCase):
    """Test cases for TransferService."""

    def setUp(self) -> None:
        self.user: UserType = cast('UserType', UserFactory())
        self.container = ApplicationContainer()
        self.transfer_service = (
            self.container.finance_account.transfer_service()
        )
        self.from_account: Account = cast(
            'Account',
            AccountFactory(
                user=self.user,
                balance=Decimal('1000.00'),
            ),
        )
        self.to_account: Account = cast(
            'Account',
            AccountFactory(
                user=self.user,
                balance=Decimal('500.00'),
            ),
        )

    def test_transfer_service_execute_transfer(self) -> None:
        """Test TransferService execute_transfer method."""
        transfer_log = self.transfer_service.transfer_money(
            from_account=self.from_account,
            to_account=self.to_account,
            amount=Decimal('200.00'),
            user=self.user,
            exchange_date=datetime(
                2024,
                1,
                1,
                tzinfo=timezone.get_current_timezone(),
            ),
            notes='Test transfer',
        )

        self.assertIsInstance(transfer_log, TransferMoneyLog)
        self.assertEqual(transfer_log.from_account, self.from_account)
        self.assertEqual(transfer_log.to_account, self.to_account)
        self.assertEqual(transfer_log.amount, Decimal('200.00'))
        self.assertEqual(transfer_log.user, self.user)
        self.assertEqual(transfer_log.notes, 'Test transfer')

        self.from_account.refresh_from_db()
        self.to_account.refresh_from_db()
        self.assertEqual(self.from_account.balance, Decimal('800.00'))
        self.assertEqual(self.to_account.balance, Decimal('700.00'))

    def test_transfer_service_insufficient_funds(self) -> None:
        """Test TransferService with insufficient funds."""
        with self.assertRaises(ValidationError):
            self.transfer_service.transfer_money(
                from_account=self.from_account,
                to_account=self.to_account,
                amount=Decimal('1500.00'),
                user=self.user,
                exchange_date=datetime(
                    2024,
                    1,
                    1,
                    tzinfo=timezone.get_current_timezone(),
                ),
                notes='Test transfer',
            )

    def test_transfer_service_same_account(self) -> None:
        """Test TransferService with same account."""
        with self.assertRaises(ValidationError):
            self.transfer_service.transfer_money(
                from_account=self.from_account,
                to_account=self.from_account,
                amount=Decimal('200.00'),
                user=self.user,
                exchange_date=datetime(
                    2024,
                    1,
                    1,
                    tzinfo=timezone.get_current_timezone(),
                ),
                notes='Test transfer',
            )

    def test_transfer_service_invalid_amounts_parametrized(self) -> None:
        """Boundary: zero and negative amounts should be rejected."""
        invalid_amounts = [
            Decimal('0.00'),
            Decimal('-0.01'),
            Decimal('-100.00'),
        ]
        for amount in invalid_amounts:
            with (
                self.subTest(amount=amount),
                self.assertRaises(ValidationError),
            ):
                self.transfer_service.transfer_money(
                    from_account=self.from_account,
                    to_account=self.to_account,
                    amount=amount,
                    user=self.user,
                    exchange_date=datetime(
                        2024,
                        1,
                        1,
                        tzinfo=timezone.get_current_timezone(),
                    ),
                    notes='Test transfer',
                )

    def test_transfer_service_amount_equals_balance_boundary(self) -> None:
        """Boundary: transferring exactly available balance should succeed."""
        transfer_amount = self.from_account.balance
        self.transfer_service.transfer_money(
            from_account=self.from_account,
            to_account=self.to_account,
            amount=transfer_amount,
            user=self.user,
            exchange_date=datetime(
                2024,
                1,
                1,
                tzinfo=timezone.get_current_timezone(),
            ),
            notes='All funds',
        )

        self.from_account.refresh_from_db()
        self.to_account.refresh_from_db()
        self.assertEqual(self.from_account.balance, Decimal('0.00'))
        self.assertEqual(self.to_account.balance, Decimal('1500.00'))

    def test_transfer_is_atomic_when_log_creation_fails(self) -> None:
        """If log creation fails, transfer is rolled back completely."""
        original_from = self.from_account.balance
        original_to = self.to_account.balance

        with (
            mock.patch(
                'hasta_la_vista_money.finance_account.repositories.transfer_money_log_repository.TransferMoneyLogRepository.create_log',
                side_effect=RuntimeError('fail on create'),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.transfer_service.transfer_money(
                from_account=self.from_account,
                to_account=self.to_account,
                amount=Decimal('200.00'),
                user=self.user,
                exchange_date=datetime(
                    2024,
                    1,
                    1,
                    tzinfo=timezone.get_current_timezone(),
                ),
                notes='Should rollback',
            )

        self.from_account.refresh_from_db()
        self.to_account.refresh_from_db()
        self.assertEqual(self.from_account.balance, original_from)
        self.assertEqual(self.to_account.balance, original_to)

    def test_sequential_large_transfers_only_first_succeeds(self) -> None:
        """Test two sequential large transfers: second should fail."""
        self.transfer_service.transfer_money(
            from_account=self.from_account,
            to_account=self.to_account,
            amount=Decimal('700.00'),
            user=self.user,
            exchange_date=datetime(
                2024,
                1,
                1,
                tzinfo=timezone.get_current_timezone(),
            ),
            notes='First',
        )

        with self.assertRaises(ValidationError):
            self.transfer_service.transfer_money(
                from_account=self.from_account,
                to_account=self.to_account,
                amount=Decimal('700.00'),
                user=self.user,
                exchange_date=datetime(
                    2024,
                    1,
                    1,
                    tzinfo=timezone.get_current_timezone(),
                ),
                notes='Second',
            )

        logs = TransferMoneyLog.objects.filter(user=self.user)
        self.assertEqual(logs.count(), 1)

    def test_delete_transfer_reverses_balance_and_removes_log(self) -> None:
        """Deleting a transfer should revert both account balances."""
        transfer_log = self.transfer_service.transfer_money(
            from_account=self.from_account,
            to_account=self.to_account,
            amount=Decimal('200.00'),
            user=self.user,
            exchange_date=datetime(
                2024,
                1,
                1,
                tzinfo=timezone.get_current_timezone(),
            ),
            notes='Delete me',
        )

        self.transfer_service.delete_transfer(
            transfer_id=transfer_log.pk,
            user=self.user,
        )

        self.from_account.refresh_from_db()
        self.to_account.refresh_from_db()
        self.assertEqual(self.from_account.balance, Decimal('1000.00'))
        self.assertEqual(self.to_account.balance, Decimal('500.00'))
        self.assertFalse(
            TransferMoneyLog.objects.filter(pk=transfer_log.pk).exists(),
        )

    def test_delete_transfer_rejects_foreign_user(self) -> None:
        """Deleting another user's transfer should be rejected."""
        other_user = UserFactory()
        transfer_log = self.transfer_service.transfer_money(
            from_account=self.from_account,
            to_account=self.to_account,
            amount=Decimal('100.00'),
            user=self.user,
            exchange_date=datetime(
                2024,
                1,
                1,
                tzinfo=timezone.get_current_timezone(),
            ),
            notes='Foreign user',
        )

        with self.assertRaises(PermissionDenied):
            self.transfer_service.delete_transfer(
                transfer_id=transfer_log.pk,
                user=other_user,
            )

        self.assertTrue(
            TransferMoneyLog.objects.filter(pk=transfer_log.pk).exists(),
        )

    def test_transfer_rejects_deposit_as_source(self) -> None:
        """Transferring from a deposit account bypasses the deposit domain."""
        deposit_account = Account.objects.create_deposit(
            user=self.user,
            name_account='Вклад',
            bank=self.from_account.bank,
            currency='RUB',
            balance=Decimal('5000.00'),
        )
        with self.assertRaises(ValidationError):
            self.transfer_service.transfer_money(
                from_account=deposit_account,
                to_account=self.to_account,
                amount=Decimal('100.00'),
                user=self.user,
                exchange_date=datetime(
                    2024,
                    1,
                    1,
                    tzinfo=timezone.get_current_timezone(),
                ),
                notes='Deposit source',
            )
        deposit_account.refresh_from_db()
        self.to_account.refresh_from_db()
        self.assertEqual(deposit_account.balance, Decimal('5000.00'))
        self.assertEqual(self.to_account.balance, Decimal('500.00'))

    def test_transfer_rejects_deposit_as_destination(self) -> None:
        """Transferring to a deposit account bypasses the deposit domain."""
        deposit_account = Account.objects.create_deposit(
            user=self.user,
            name_account='Вклад',
            bank=self.from_account.bank,
            currency='RUB',
            balance=Decimal('5000.00'),
        )
        with self.assertRaises(ValidationError):
            self.transfer_service.transfer_money(
                from_account=self.from_account,
                to_account=deposit_account,
                amount=Decimal('100.00'),
                user=self.user,
                exchange_date=datetime(
                    2024,
                    1,
                    1,
                    tzinfo=timezone.get_current_timezone(),
                ),
                notes='Deposit destination',
            )
        deposit_account.refresh_from_db()
        self.from_account.refresh_from_db()
        self.assertEqual(deposit_account.balance, Decimal('5000.00'))
        self.assertEqual(self.from_account.balance, Decimal('1000.00'))

    def test_transfer_rejects_different_currencies(self) -> None:
        """Transfers between accounts of different currencies are rejected."""
        foreign_account: Account = cast(
            'Account',
            AccountFactory(
                user=self.user,
                balance=Decimal('500.00'),
                currency='USD',
            ),
        )
        with self.assertRaises(ValidationError):
            self.transfer_service.transfer_money(
                from_account=self.from_account,
                to_account=foreign_account,
                amount=Decimal('100.00'),
                user=self.user,
                exchange_date=datetime(
                    2024,
                    1,
                    1,
                    tzinfo=timezone.get_current_timezone(),
                ),
                notes='Cross-currency',
            )

        self.from_account.refresh_from_db()
        foreign_account.refresh_from_db()
        self.assertEqual(self.from_account.balance, Decimal('1000.00'))
        self.assertEqual(foreign_account.balance, Decimal('500.00'))
        self.assertFalse(
            TransferMoneyLog.objects.filter(user=self.user).exists(),
        )

    def test_delete_transfer_rejects_deposit_as_source(self) -> None:
        """Deposit withdrawals cannot be deleted as plain transfers."""
        deposit_account = Account.objects.create_deposit(
            user=self.user,
            name_account='Вклад',
            bank=self.from_account.bank,
            currency='RUB',
            balance=Decimal('5000.00'),
        )
        transfer_log = TransferMoneyLog.objects.create(
            user=self.user,
            from_account=deposit_account,
            to_account=self.to_account,
            amount=Decimal('100.00'),
            exchange_date=datetime(
                2024,
                1,
                1,
                tzinfo=timezone.get_current_timezone(),
            ),
            notes='Частичное снятие тела вклада',
        )

        with self.assertRaises(ValidationError):
            self.transfer_service.delete_transfer(
                transfer_id=transfer_log.pk,
                user=self.user,
            )

        deposit_account.refresh_from_db()
        self.to_account.refresh_from_db()
        self.assertEqual(deposit_account.balance, Decimal('5000.00'))
        self.assertEqual(self.to_account.balance, Decimal('500.00'))
        self.assertTrue(
            TransferMoneyLog.objects.filter(pk=transfer_log.pk).exists(),
        )

    def test_delete_transfer_rejects_deposit_as_destination(self) -> None:
        """Deposit funding cannot be deleted as a plain transfer."""
        deposit_account = Account.objects.create_deposit(
            user=self.user,
            name_account='Вклад',
            bank=self.from_account.bank,
            currency='RUB',
            balance=Decimal('5000.00'),
        )
        transfer_log = TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.from_account,
            to_account=deposit_account,
            amount=Decimal('100.00'),
            exchange_date=datetime(
                2024,
                1,
                1,
                tzinfo=timezone.get_current_timezone(),
            ),
            notes='Пополнение тела вклада',
        )

        with self.assertRaises(ValidationError):
            self.transfer_service.delete_transfer(
                transfer_id=transfer_log.pk,
                user=self.user,
            )

        deposit_account.refresh_from_db()
        self.from_account.refresh_from_db()
        self.assertEqual(deposit_account.balance, Decimal('5000.00'))
        self.assertEqual(self.from_account.balance, Decimal('1000.00'))
        self.assertTrue(
            TransferMoneyLog.objects.filter(pk=transfer_log.pk).exists(),
        )
