"""Dashboard JSON widgets are shown in the analytics currency."""

from decimal import Decimal
from typing import Any

from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.budget.models import Planning
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import FamilyGroupMembership, User


class DashboardDataCurrencyTest(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.user = User.objects.create_user(username='dashboard-currency')
        self.client.force_login(self.user)
        category = Category.objects.create(
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
            Planning.objects.create(
                user=self.user,
                category=category,
                date=timezone.localdate().replace(day=1),
                amount=Decimal(amount) * 10,
                planning_type=TransactionType.EXPENSE,
                currency=currency,
            )

    def _data(self, currency: str) -> dict[str, Any]:
        response = self.client.get(
            reverse('users:dashboard_data'),
            {'currency': currency},
        )
        self.assertEqual(response.status_code, 200)
        data: dict[str, Any] = response.json()
        return data

    def _widget_totals(self, data: dict[str, Any]) -> dict[str, float]:
        analytics = data['analytics']
        months = analytics['stats']['months_data']
        return {
            'months': sum(month['expenses'] for month in months),
            'planned': sum(month['planned_expenses'] for month in months),
            'top': sum(
                float(item['total'])
                for item in analytics['stats']['top_expense_categories']
            ),
            'heatmap': sum(day[1] for day in analytics['expense_heatmap']),
            'comparison': data['comparison']['current']['expenses'],
        }

    def test_widgets_use_selected_currency_without_cache_leak(self) -> None:
        usd = self._data('USD')
        rub = self._data('RUB')

        self.assertEqual(usd['currency'], 'USD')
        self.assertEqual(
            self._widget_totals(usd),
            dict.fromkeys(('months', 'top', 'heatmap', 'comparison'), 7.0)
            | {'planned': 70.0},
        )
        self.assertEqual(rub['currency'], 'RUB')
        self.assertEqual(
            self._widget_totals(rub),
            dict.fromkeys(('months', 'top', 'heatmap', 'comparison'), 300.0)
            | {'planned': 3000.0},
        )

    def test_drilldown_uses_selected_currency(self) -> None:
        self._data('USD')
        url = reverse('users:dashboard_drilldown')

        top = self.client.get(url, {'currency': 'USD'}).json()['data']
        category = self.client.get(
            url,
            {'category_id': top[0]['category_id'], 'currency': 'USD'},
        ).json()['data']

        self.assertEqual([item['value'] for item in top], [7.0])
        self.assertEqual([item['value'] for item in category], [7.0])

    def test_comparison_endpoint_uses_selected_currency(self) -> None:
        self._data('USD')

        response = self.client.get(
            reverse('users:dashboard_comparison'),
            {'currency': 'USD'},
        )

        self.assertEqual(response.json()['current']['expenses'], 7.0)


class DashboardDataFamilyCurrencyTest(TestCase):
    def test_widgets_ignore_family_currency_the_user_lacks(self) -> None:
        cache.clear()
        user = User.objects.create_user(username='dashboard-own')
        spouse = User.objects.create_user(username='dashboard-spouse')
        group = Group.objects.create(name='dashboard-family')
        for member in (user, spouse):
            FamilyGroupMembership.objects.create(group=group, user=member)
        Account.objects.create(user=user, name_account='RUB', currency='RUB')
        Account.objects.create(
            user=spouse,
            name_account='USD',
            currency='USD',
        )
        self.client.force_login(user)
        self.client.get(reverse('users:dashboard'), {'currency': 'USD'})

        response = self.client.get(reverse('users:dashboard_data'))

        self.assertEqual(response.json()['currency'], 'RUB')
        self.assertEqual(
            self.client.session[constants.ANALYTICS_CURRENCY_SESSION_KEY],
            'USD',
        )
