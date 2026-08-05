"""Tests for reports Celery tasks."""

import inspect
from datetime import UTC, date, datetime
from decimal import Decimal

from django.test import TestCase

from config.containers import ApplicationContainer
from hasta_la_vista_money.deposits.commands import CreateDepositCommand
from hasta_la_vista_money.deposits.models import (
    DepositCapitalizationEvent,
    DepositInterestForecast,
    DepositTerm,
)
from hasta_la_vista_money.finance_account.models import Account, Bank
from hasta_la_vista_money.reports.tasks import (
    generate_monthly_report,
    generate_user_statistics,
    generate_yearly_report,
)
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User


class ReportTaskTests(TestCase):
    """Reports tasks should be regular Celery tasks."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='reports-user',
            password='pass',  # nosec B106: test-only password
        )

    def test_report_generators_are_celery_tasks(self) -> None:
        """Expose Celery task API instead of coroutine functions."""
        for task in (
            generate_monthly_report,
            generate_yearly_report,
            generate_user_statistics,
        ):
            self.assertTrue(hasattr(task, 'delay'))
            self.assertFalse(inspect.iscoroutinefunction(task.run))

    def test_generate_monthly_report_returns_success(self) -> None:
        """Generate an empty monthly report synchronously via task run."""
        result = generate_monthly_report.run(self.user.pk, 2026, 1)

        self.assertTrue(result['success'])
        self.assertEqual(result['report']['period']['year'], 2026)
        self.assertEqual(result['report']['period']['month'], 1)

    def test_monthly_report_includes_last_day_and_excludes_next_month(
        self,
    ) -> None:
        account = Account.objects.create(user=self.user, name_account='Main')
        category = Category.objects.create(
            user=self.user,
            name='Salary',
            type=TransactionType.INCOME,
        )
        for transaction_date, amount in (
            (datetime(2026, 1, 31, 23, 59, tzinfo=UTC), Decimal('900.00')),
            (datetime(2026, 2, 1, 0, 0, tzinfo=UTC), Decimal('100.00')),
        ):
            Transaction.objects.create(
                user=self.user,
                account=account,
                category=category,
                type=TransactionType.INCOME,
                amount=amount,
                date=transaction_date,
            )

        result = generate_monthly_report.run(self.user.pk, 2026, 1)

        self.assertTrue(result['success'])
        self.assertEqual(
            result['report']['income']['total_income'],
            Decimal('900.00'),
        )

    def test_generate_yearly_report_returns_success(self) -> None:
        """Generate an empty yearly report synchronously via task run."""
        result = generate_yearly_report.run(self.user.pk, 2026)

        self.assertTrue(result['success'])
        self.assertEqual(result['report']['year'], 2026)

    def test_generate_user_statistics_returns_success(self) -> None:
        """Generate empty user statistics synchronously via task run."""
        result = generate_user_statistics.run(self.user.pk)

        self.assertTrue(result['success'])
        self.assertEqual(result['statistics']['user_id'], self.user.pk)

    def test_reports_count_actual_interest_once_and_ignore_forecast(
        self,
    ) -> None:
        bank, _ = Bank.objects.get_or_create(
            code='SBERBANK',
            defaults={'name': 'Сбербанк', 'is_system': True},
        )
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=self.user,
                name='Вклад',
                bank=bank,
                currency='RUB',
                balance=Decimal('1000.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        DepositInterestForecast.objects.create(
            term=deposit.current_term,
            payout_on=date(2026, 1, 15),
            amount=Decimal('999.00'),
            period_starts_on=date(2026, 1, 1),
            period_ends_on=date(2026, 1, 15),
        )
        DepositCapitalizationEvent.objects.create(
            deposit=deposit,
            gross=Decimal('100.00'),
            withholding=Decimal('13.00'),
            net=Decimal('87.00'),
            posting_on=date(2026, 1, 15),
            value_on=date(2026, 1, 15),
        )

        monthly = generate_monthly_report.run(self.user.pk, 2026, 1)
        yearly = generate_yearly_report.run(self.user.pk, 2026)
        overall = generate_user_statistics.run(self.user.pk)

        self.assertEqual(
            monthly['report']['income']['total_income'],
            Decimal('100.00'),
        )
        self.assertEqual(
            monthly['report']['expense']['total_expense'],
            Decimal('13.00'),
        )
        self.assertEqual(
            yearly['report']['summary']['net_income'],
            Decimal('87.00'),
        )
        self.assertEqual(
            overall['statistics']['summary']['net_worth'],
            Decimal('87.00'),
        )
