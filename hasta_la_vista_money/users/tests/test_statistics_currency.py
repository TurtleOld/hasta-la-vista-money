"""Detailed statistics are shown in the analytics currency."""

from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from hasta_la_vista_money.budget.models import Budget, Planning
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User


class StatisticsCurrencyTest(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.user = User.objects.create_user(username='stats-currency')
        self.client.force_login(self.user)
        self.category = category = Category.objects.create(
            user=self.user,
            name='Food',
            type=TransactionType.EXPENSE,
        )
        for currency, amount in (('RUB', '300.00'), ('USD', '7.00')):
            Transaction.objects.create(
                user=self.user,
                account=Account.objects.create(
                    user=self.user,
                    name_account=currency,
                    currency=currency,
                ),
                category=category,
                type=TransactionType.EXPENSE,
                amount=Decimal(amount),
                date=timezone.now(),
            )

    def _month_expenses(self, query: str = '') -> float:
        response = self.client.get(f'{reverse("users:statistics")}{query}')
        self.assertEqual(response.status_code, 200)
        return sum(
            float(month['expenses'])
            for month in response.context['months_data']
        )

    def test_default_currency_excludes_other_currency(self) -> None:
        self.assertEqual(self._month_expenses(), 300.0)

    def test_account_choices_only_in_selected_currency(self) -> None:
        response = self.client.get(reverse('users:statistics'))

        self.assertEqual(
            [
                account.currency
                for account in response.context['statistics_account_choices']
            ],
            ['RUB'],
        )

    def test_budget_and_plan_fact_exclude_other_currency(self) -> None:
        month = timezone.localdate().replace(day=1)
        category = self.category
        for currency, amount in (('RUB', 1000), ('USD', 50)):
            Budget.objects.create(
                user=self.user,
                category=category,
                period=month,
                amount_limit=Decimal(amount),
                currency=currency,
            )
            Planning.objects.create(
                user=self.user,
                category=category,
                date=month,
                amount=Decimal(amount),
                planning_type=TransactionType.EXPENSE,
                currency=currency,
            )

        response = self.client.get(reverse('users:statistics'))

        context = response.context
        budgets = context['budgets_data']
        self.assertEqual(
            [(b['amount_limit'], b['actual_expenses']) for b in budgets],
            [(1000.0, 300.0)],
        )
        self.assertEqual(
            sum(m['planned_expenses'] for m in context['months_data']),
            1000.0,
        )
        summary = context['plan_fact_summary']['expense']
        self.assertEqual((summary['fact'], summary['plan']), (300.0, 1000.0))
        deviations = context['plan_fact_top_deviations']
        self.assertEqual(
            [(d['fact'], d['plan']) for d in deviations],
            [(300.0, 1000.0)],
        )
        self.assertEqual(context['plan_fact_engagement']['diff'], -700.0)

    def test_switching_currency_is_not_served_from_previous_cache(
        self,
    ) -> None:
        self.assertEqual(self._month_expenses('?currency=RUB'), 300.0)
        self.assertEqual(self._month_expenses('?currency=USD'), 7.0)
        self.assertEqual(self._month_expenses(), 7.0)
