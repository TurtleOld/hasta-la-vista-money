"""Cross-feature regressions for the accounting-control statement domain.

These tests deliberately span more than one ticket: statement decisions and
retention are checked against money, audit, budget and statistics, not only
against the statement tables themselves.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, cast

from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.system.models import AuditLog
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    FamilyGroupMembership,
    User,
)

ACCOUNT_LABEL = 'finance_account.Account'


def _balance_movements(account_id: int) -> list[tuple[Decimal, Decimal]]:
    """Return the audited (old, new) balance pairs of one account."""
    movements: list[tuple[Decimal, Decimal]] = []
    logs = AuditLog.objects.filter(
        model_name=ACCOUNT_LABEL,
        object_pk=str(account_id),
    ).order_by('pk')
    for log in logs:
        diff: dict[str, Any] = log.diff
        if log.action == AuditLog.Action.CREATE:
            created = diff.get('created', {})
            if 'balance' in created:
                opening = Decimal(created['balance'])
                movements.append((opening, opening))
            continue
        changed = diff.get('changed', {})
        if 'balance' in changed:
            movements.append(
                (
                    Decimal(changed['balance']['old']),
                    Decimal(changed['balance']['new']),
                ),
            )
    return movements


class StatementFinancialRegressionFixture(TestCase):
    """One owner, one rouble account and a row awaiting markup."""

    def setUp(self) -> None:
        cache.clear()
        self.user = User.objects.create_user(username='cross-feature-owner')
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной счёт',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.expense_category = Category.objects.create(
            user=self.user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        self.income_category = Category.objects.create(
            user=self.user,
            name='Зарплата',
            type=TransactionType.INCOME,
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='statement.pdf',
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.container = ApplicationContainer()
        self.today = timezone.localdate()
        self.moment = datetime.combine(
            self.today,
            time(12, 0),
            tzinfo=timezone.get_current_timezone(),
        )

    def _row(
        self,
        position: int = 1,
        *,
        decision: str = BankStatementRow.Decision.AWAITING_MARKUP,
        transaction_type: str = BankStatementRow.TransactionType.EXPENSE,
        amount: str = '100.00',
    ) -> BankStatementRow:
        return BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type=transaction_type,
            transaction_date=self.moment,
            bank_calendar_date=self.today,
            date_precision=BankStatementRow.DatePrecision.DAY,
            amount=Decimal(amount),
            description='ПЯТЁРОЧКА',
            source_ref=f'{position}-{self.today:%d.%m.%Y}',
            source_ref_hash=f'hash-{position}',
            source_row_position=position,
            kind='card',
            decision=decision,
        )

    def _post(self, row: BankStatementRow) -> BankStatementRow:
        return cast(
            'BankStatementRow',
            self.container.users.statement_markup_service().post(
                row.pk,
                self.user.pk,
                self.expense_category.pk,
            ),
        )

    def _cleanup(self) -> int:
        BankStatementUpload.objects.filter(pk=self.upload.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        service = self.container.users.bank_statement_retention_service()
        return cast('int', service.cleanup_expired())

    def _budget(self) -> dict[str, Any]:
        return cast(
            'dict[str, Any]',
            self.container.budget.budget_service().aggregate_budget_data(
                user=self.user,
                months=[self.today.replace(day=1)],
                expense_categories=[self.expense_category],
                income_categories=[self.income_category],
                currency='RUB',
            ),
        )

    def _statistics(self) -> dict[str, Any]:
        return cast(
            'dict[str, Any]',
            self.container.users.user_statistics_service().get_user_statistics(
                self.user,
                'RUB',
            ),
        )

    def _expense_total(self) -> Decimal:
        return sum(
            (row['fact'][0] for row in self._budget()['expense_data']),
            Decimal(0),
        )

    def _assert_chain_ends_at_balance(self) -> None:
        movements = _balance_movements(self.account.pk)
        self.account.refresh_from_db(fields=['balance'])
        if not movements:
            self.fail('У счёта нет аудита остатка')
        self.assertEqual(movements[-1][1], self.account.balance)


class StatementDecisionFinancialRegressionTest(
    StatementFinancialRegressionFixture,
):
    """Deferring, excluding and resuming never touch financial data."""

    def test_suspended_rows_leave_money_budget_and_statistics_unchanged(
        self,
    ) -> None:
        row = self._row()
        balance_audit_before = _balance_movements(self.account.pk)
        budget_before = self._budget()
        statistics_before = self._statistics()

        service = self.container.users.statement_row_link_service()
        service.defer(row.pk, self.user.pk)
        service.resume(row.pk, self.user.pk)
        service.exclude(row.pk, self.user.pk, 'Оплата наличными')
        service.resume(row.pk, self.user.pk)

        self.account.refresh_from_db(fields=['balance'])
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(
            _balance_movements(self.account.pk),
            balance_audit_before,
        )
        self.assertEqual(self._budget(), budget_before)
        self.assertEqual(self._statistics(), statistics_before)
        row.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertEqual(row.decision_reason, '')

    def test_family_viewer_cannot_read_or_decide_statement_rows(self) -> None:
        row = self._row()
        viewer = User.objects.create_user(username='cross-feature-viewer')
        group = Group.objects.create(name='Семья')
        FamilyGroupMembership.objects.create(
            group=group,
            user=self.user,
            role=FamilyGroupMembership.Role.OWNER,
        )
        FamilyGroupMembership.objects.create(
            group=group,
            user=viewer,
            role=FamilyGroupMembership.Role.VIEWER,
        )
        self.client.force_login(viewer)

        page = self.client.get(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[self.upload.pk],
            ),
        )
        decision = self.client.post(
            reverse(
                'finance_account:bank_statement_row_defer',
                args=[self.upload.pk, row.pk],
            ),
        )

        self.assertEqual(page.status_code, 404)
        self.assertEqual(decision.status_code, 404)
        row.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertFalse(Transaction.objects.exists())


class StatementRetentionFinancialRegressionTest(
    StatementFinancialRegressionFixture,
):
    """Retention drops bank details without rewriting financial accounting."""

    def _posted_row(self) -> BankStatementRow:
        row = self._row()
        posted = self._post(row)
        self.assertEqual(posted.decision, BankStatementRow.Decision.NEW)
        self.assertIsNotNone(posted.transaction_id)
        return posted

    def test_cleanup_preserves_movement_balance_budget_and_statistics(
        self,
    ) -> None:
        row = self._posted_row()
        transaction_id = cast('int', row.transaction_id)
        chain_before = _balance_movements(self.account.pk)
        budget_before = self._budget()
        statistics_before = self._statistics()
        self.account.refresh_from_db(fields=['balance'])
        self.assertEqual(self.account.balance, Decimal('900.00'))

        self.assertEqual(self._cleanup(), 1)

        row.refresh_from_db()
        self.account.refresh_from_db(fields=['balance'])
        self.assertTrue(Transaction.objects.filter(pk=transaction_id).exists())
        self.assertEqual(row.transaction_id, transaction_id)
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)
        self.assertEqual(self.account.balance, Decimal('900.00'))
        self.assertEqual(_balance_movements(self.account.pk), chain_before)
        self.assertEqual(self._budget(), budget_before)
        self.assertEqual(self._statistics(), statistics_before)
        self.assertIsNotNone(row.data_cleaned_at)
        self.assertIsNone(row.amount)
        self.assertIsNone(row.transaction_date)
        self.assertEqual(row.description, '')

    def test_deleting_linked_movement_after_cleanup_reopens_without_data(
        self,
    ) -> None:
        row = self._posted_row()
        transaction = Transaction.objects.get(
            pk=cast('int', row.transaction_id),
        )
        self.assertEqual(self._cleanup(), 1)
        cache.clear()

        self.container.transactions.transaction_service().delete_transaction(
            user=self.user,
            transaction_obj=transaction,
        )

        row.refresh_from_db()
        self.account.refresh_from_db(fields=['balance'])
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        self.assertIsNone(row.transaction_id)
        self.assertIsNone(row.amount)
        self.assertIsNone(row.transaction_date)
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(self._expense_total(), Decimal(0))
        statistics = self._statistics()
        self.assertEqual(statistics['current_month_expenses'], Decimal(0))
        self._assert_chain_ends_at_balance()

    def test_cleanup_does_not_copy_bank_amount_into_audit(self) -> None:
        self._posted_row()
        audit_before = list(
            AuditLog.objects.values_list('pk', 'diff').order_by('pk'),
        )

        self.assertEqual(self._cleanup(), 1)

        audit_after = list(
            AuditLog.objects.values_list('pk', 'diff').order_by('pk'),
        )
        self.assertEqual(audit_after, audit_before)


class StatementCurrencyIsolationRegressionTest(
    StatementFinancialRegressionFixture,
):
    """A rouble statement row never changes dollar totals."""

    def test_posting_rub_row_does_not_change_usd_totals(self) -> None:
        usd_account = Account.objects.create(
            user=self.user,
            name_account='Долларовый счёт',
            balance=Decimal('100.00'),
            currency='USD',
        )
        Transaction.objects.create(
            user=self.user,
            account=usd_account,
            category=self.expense_category,
            amount=Decimal('10.00'),
            date=self.moment,
            type=TransactionType.EXPENSE,
        )
        usd_before = usd_account.balance
        usd_expenses_before = Transaction.objects.filter(
            account=usd_account,
        ).count()

        row = self._row()
        self._post(row)

        usd_account.refresh_from_db(fields=['balance'])
        self.assertEqual(usd_account.balance, usd_before)
        self.assertEqual(
            Transaction.objects.filter(account=usd_account).count(),
            usd_expenses_before,
        )
        self.account.refresh_from_db(fields=['balance'])
        self.assertEqual(self.account.balance, Decimal('900.00'))
        self.assertEqual(self._expense_total(), Decimal('100.00'))


class StatementDateRegressionTest(StatementFinancialRegressionFixture):
    """A known bank day survives posting regardless of the local clock."""

    def test_posted_movement_keeps_the_bank_calendar_day(self) -> None:
        bank_day = date(2026, 3, 1)
        row = self._row()
        row.transaction_date = datetime(
            2026,
            3,
            1,
            23,
            30,
            tzinfo=timezone.get_current_timezone(),
        )
        row.bank_calendar_date = bank_day
        row.date_precision = BankStatementRow.DatePrecision.DAY
        row.save(
            update_fields=[
                'transaction_date',
                'bank_calendar_date',
                'date_precision',
            ],
        )

        posted = self._post(row)

        transaction = Transaction.objects.get(
            pk=cast('int', posted.transaction_id),
        )
        self.assertEqual(transaction.bank_calendar_date, bank_day)
