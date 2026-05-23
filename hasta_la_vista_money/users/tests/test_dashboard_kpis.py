"""Tests for dashboard KPI calculations."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.services.dashboard_kpis import (
    get_dashboard_month_kpis,
)

User = get_user_model()


class DashboardKpiTest(TestCase):
    """Test current-month dashboard KPI aggregation."""

    def test_get_dashboard_month_kpis(self) -> None:
        user = User.objects.create_user(username='dashboard-user')
        account = Account.objects.create(user=user, name_account='Main')
        expense_category = Category.objects.create(
            user=user,
            name='Food',
            type=TransactionType.EXPENSE,
        )
        income_category = Category.objects.create(
            user=user,
            name='Salary',
            type=TransactionType.INCOME,
        )
        operation_date = timezone.now()

        Transaction.objects.create(
            user=user,
            account=account,
            category=income_category,
            type=TransactionType.INCOME,
            amount=Decimal('1000.00'),
            date=operation_date,
        )
        Transaction.objects.create(
            user=user,
            account=account,
            category=expense_category,
            type=TransactionType.EXPENSE,
            amount=Decimal('250.00'),
            date=operation_date,
        )

        kpis = get_dashboard_month_kpis(user)

        self.assertEqual(kpis['income'], Decimal(1000))
        self.assertEqual(kpis['expenses'], Decimal(250))
        self.assertEqual(kpis['net_result'], Decimal(750))
        self.assertEqual(kpis['savings_rate'], Decimal('75.00'))
        self.assertEqual(kpis['top_expense_category_id'], expense_category.pk)
        self.assertEqual(kpis['top_expense_category_name'], 'Food')
        self.assertEqual(kpis['top_expense_category_total'], Decimal(250))
