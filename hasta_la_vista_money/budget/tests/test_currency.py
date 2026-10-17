"""Budget limits and plans are expressed in one currency."""

from datetime import date, datetime
from decimal import Decimal
from http import HTTPStatus

from django.db import IntegrityError, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.budget.models import Budget, DateList, Planning
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User

MONTH = date(2026, 2, 1)


class BudgetCurrencyTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='currency_user',
            password='pass',  # nosec B106: test-only password
        )
        self.category = Category.objects.create(
            user=self.user,
            name='Food',
            type=TransactionType.EXPENSE,
        )
        self.rub = Account.objects.create(
            user=self.user,
            name_account='RUB',
            currency='RUB',
        )
        self.usd = Account.objects.create(
            user=self.user,
            name_account='USD',
            currency='USD',
        )
        DateList.objects.create(user=self.user, date=MONTH)

    def _expense(self, account: Account, amount: str) -> None:
        Transaction.objects.create(
            user=self.user,
            account=account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal(amount),
            date=datetime(2026, 2, 10, tzinfo=timezone.get_current_timezone()),
        )

    def _limit(self, currency: str, amount: str) -> Budget:
        return Budget.objects.create(
            user=self.user,
            period=MONTH,
            category=self.category,
            currency=currency,
            amount_limit=Decimal(amount),
        )

    def test_usd_expense_not_in_rub_limit_fact(self) -> None:
        self._limit('RUB', '1000')
        self._expense(self.rub, '100')
        self._expense(self.usd, '50')
        Planning.objects.create(
            user=self.user,
            category=self.category,
            date=MONTH,
            currency='USD',
            amount=Decimal(70),
        )

        service = ApplicationContainer().budget.budget_service()
        overview = service.aggregate_budget_limit_overview(
            user=self.user,
            months=[MONTH],
            expense_categories=[self.category],
            currency='RUB',
        )
        table = service.aggregate_expense_table(
            user=self.user,
            months=[MONTH],
            expense_categories=[self.category],
            currency='RUB',
        )

        self.assertEqual(overview['category_limits'][0]['fact'], Decimal(100))
        self.assertEqual(overview['category_limits'][0]['limit'], 1000)
        self.assertEqual(table['expense_data'][0]['fact'], [Decimal(100)])
        self.assertEqual(table['expense_data'][0]['plan'], [Decimal(0)])

    def test_rub_and_usd_limits_coexist_same_currency_conflicts(self) -> None:
        self._limit('RUB', '1000')
        self._limit('USD', '10')

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._limit('USD', '20')

    def test_budget_page_shows_only_limits_in_analytics_currency(
        self,
    ) -> None:
        self._limit('RUB', '1111')
        self._limit('USD', '2222')
        self.client.force_login(self.user)

        response = self.client.get(reverse('budget:list'), {'currency': 'USD'})

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertContains(response, '2222')
        self.assertNotContains(response, '1111')
        self.assertContains(
            response,
            '<input type="hidden" name="currency" value="USD">',
        )

    def test_new_limit_defaults_to_analytics_currency(self) -> None:
        self.client.force_login(self.user)
        self.client.get(reverse('budget:list'), {'currency': 'USD'})

        response = self.client.post(
            reverse('budget:save_limit'),
            {
                'category_id': self.category.pk,
                'month': MONTH.isoformat(),
                'amount_limit': 300,
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertEqual(
            Budget.objects.get(category=self.category).currency,
            'USD',
        )

    def test_unknown_currency_rejected(self) -> None:
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('budget:save_limit'),
            {
                'category_id': self.category.pk,
                'month': MONTH.isoformat(),
                'amount_limit': 300,
                'currency': ['USD'],
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        self.assertFalse(Budget.objects.exists())


class BudgetCurrencyMigrationTest(TransactionTestCase):
    migrate_from = [('budget', '0004_drop_planning_type_check')]
    migrate_to = [('budget', '0005_budget_planning_currency')]

    def tearDown(self) -> None:
        executor = MigrationExecutor(transaction.get_connection())
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_existing_limit_gets_rub(self) -> None:
        executor = MigrationExecutor(transaction.get_connection())
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        user = User.objects.create_user(username='migration_user')
        old_apps.get_model('budget', 'Budget').objects.create(
            user_id=user.pk,
            period=MONTH,
            amount_limit=Decimal(500),
        )

        executor = MigrationExecutor(transaction.get_connection())
        executor.migrate(self.migrate_to)
        new_apps = executor.loader.project_state(self.migrate_to).apps

        budget = new_apps.get_model('budget', 'Budget').objects.get()
        self.assertEqual(budget.currency, 'RUB')
