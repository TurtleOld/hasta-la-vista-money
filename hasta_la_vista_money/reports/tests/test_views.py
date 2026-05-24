"""Tests for reports views."""

from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.reports.views import ReportsAnalyticMixin, ReportView
from hasta_la_vista_money.transactions.models import Category, TransactionType

User = get_user_model()


class ReportViewTest(TestCase):
    """Test cases for ReportView."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='reports_user',
            password='pass',  # nosec B106: test-only password
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Checking',
            balance=Decimal('1000.00'),
        )
        self.expense_category = Category.objects.create(
            user=self.user,
            name='Groceries',
            type=TransactionType.EXPENSE,
        )
        self.income_category = Category.objects.create(
            user=self.user,
            name='Salary',
            type=TransactionType.INCOME,
        )
        self.factory = RequestFactory()

    def test_collect_datasets_authenticated(self) -> None:
        request = self.factory.get('/')
        request.user = self.user
        expense_dataset, income_dataset = ReportView.collect_datasets(request)
        self.assertIsNotNone(expense_dataset)
        self.assertIsNotNone(income_dataset)

    def test_collect_datasets_anonymous_user(self) -> None:
        request = self.factory.get('/')
        request.user = AnonymousUser()
        with self.assertRaises(TypeError):
            ReportView.collect_datasets(request)

    def test_transform_data(self) -> None:
        dataset = [
            {'date': '2025-01-01', 'total_amount': 100.0},
            {'date': '2025-01-02', 'total_amount': 200.0},
        ]
        dates, amounts = ReportView.transform_data(dataset)
        self.assertEqual(len(dates), 2)
        self.assertEqual(len(amounts), 2)

    def test_transform_data_expense(self) -> None:
        dataset = [
            {'date': '2025-01-01', 'total_amount': 100.0},
        ]
        dates, amounts = ReportView.transform_data_expense(dataset)
        self.assertEqual(len(dates), 1)
        self.assertEqual(len(amounts), 1)

    def test_transform_data_income(self) -> None:
        dataset = [
            {'date': '2025-01-01', 'total_amount': 100.0},
        ]
        dates, amounts = ReportView.transform_data_income(dataset)
        self.assertEqual(len(dates), 1)
        self.assertEqual(len(amounts), 1)

    def test_unique_data(self) -> None:
        dates = ['2025-01-01', '2025-01-01', '2025-01-02']
        amounts = [10.0, 5.0, 3.0]
        u_dates, u_amounts = ReportView.unique_data(dates, amounts)
        self.assertEqual(len(u_dates), 2)
        self.assertEqual(u_amounts[0], 15.0)

    def test_unique_expense_data(self) -> None:
        dates = ['2025-01-01', '2025-01-01']
        amounts = [10.0, 5.0]
        u_dates, u_amounts = ReportView.unique_expense_data(dates, amounts)
        self.assertEqual(len(u_dates), 1)
        self.assertEqual(u_amounts[0], 15.0)

    def test_unique_income_data(self) -> None:
        dates = ['2025-01-01', '2025-01-01']
        amounts = [10.0, 5.0]
        u_dates, u_amounts = ReportView.unique_income_data(dates, amounts)
        self.assertEqual(len(u_dates), 1)
        self.assertEqual(u_amounts[0], 15.0)

    def test_pie_expense_category_authenticated(self) -> None:
        request = self.factory.get('/')
        request.user = self.user
        charts_data = ReportView.pie_expense_category(request)
        self.assertIsInstance(charts_data, list)

    def test_pie_expense_category_anonymous_user(self) -> None:
        request = self.factory.get('/')
        request.user = AnonymousUser()
        with self.assertRaises(TypeError):
            ReportView.pie_expense_category(request)

    def test_get_method(self) -> None:
        self.client.force_login(self.user)
        with patch.object(ReportView, 'prepare_budget_charts') as mock_prepare:
            mock_prepare.return_value = {'test': 'data'}
            view = ReportView()
            view.request = self.factory.get('/')
            view.request.user = self.user
            response = view.get(view.request)
            self.assertEqual(response.status_code, 200)

    def test_get_expense_data(self) -> None:
        view = ReportView()
        months = [date(2025, 1, 1)]
        result = view._get_expense_data(
            self.user,
            [self.expense_category],
            months,
        )
        self.assertIsInstance(result, dict)

    def test_get_expense_data_empty_months(self) -> None:
        view = ReportView()
        result = view._get_expense_data(self.user, [self.expense_category], [])
        self.assertIsInstance(result, dict)
        self.assertEqual(len(result), 0)

    def test_get_income_data(self) -> None:
        view = ReportView()
        months = [date(2025, 1, 1)]
        result = view._get_income_data(
            self.user,
            [self.income_category],
            months,
        )
        self.assertIsInstance(result, dict)

    def test_get_income_data_empty_months(self) -> None:
        view = ReportView()
        result = view._get_income_data(self.user, [self.income_category], [])
        self.assertIsInstance(result, dict)
        self.assertEqual(len(result), 0)

    def test_calculate_totals(self) -> None:
        view = ReportView()
        months = [date(2025, 1, 1)]
        fact_map: dict[int, dict[date, Decimal | int]] = {
            self.expense_category.pk: {months[0]: Decimal('100.00')},
        }
        totals = view._calculate_totals(
            [self.expense_category],
            months,
            fact_map,
        )
        self.assertIsInstance(totals, list)
        self.assertEqual(len(totals), 1)

    def test_calculate_category_totals(self) -> None:
        view = ReportView()
        months = [date(2025, 1, 1)]
        fact_map: dict[int, dict[date, Decimal | int]] = {
            self.expense_category.pk: {months[0]: Decimal('100.00')},
        }
        totals = view._calculate_category_totals(
            [self.expense_category],
            months,
            fact_map,
        )
        self.assertIsInstance(totals, dict)
        self.assertIn(self.expense_category.pk, totals)

    def test_calculate_pie_data(self) -> None:
        view = ReportView()
        months = [date(2025, 1, 1)]
        fact_map: dict[int, dict[date, Decimal | int]] = {
            self.expense_category.pk: {months[0]: Decimal('100.00')},
        }
        labels, values = view._calculate_pie_data(
            [self.expense_category],
            months,
            fact_map,
        )
        self.assertIsInstance(labels, list)
        self.assertIsInstance(values, list)

    def test_calculate_pie_data_empty(self) -> None:
        view = ReportView()
        labels, values = view._calculate_pie_data([], [], {})
        self.assertEqual(len(labels), 0)
        self.assertEqual(len(values), 0)

    def test_prepare_budget_charts(self) -> None:
        request = self.factory.get('/')
        request.user = self.user
        view = ReportView()
        view.request = request
        charts_data = view.prepare_budget_charts(request)
        self.assertIsInstance(charts_data, dict)

    @patch('hasta_la_vista_money.reports.views.budget_charts')
    def test_prepare_budget_charts_avoids_extra_user_lookup(
        self,
        mock_budget_charts: Any,
    ) -> None:
        request = self.factory.get('/')
        request.user = self.user
        view = ReportView()
        view.request = request
        mock_budget_charts.return_value = {}

        with CaptureQueriesContext(connection) as queries:
            charts_data = view.prepare_budget_charts(request)

        self.assertEqual(charts_data, {})
        self.assertEqual(len(queries), 0)
        mock_budget_charts.assert_called_once_with(self.user)

    def test_prepare_budget_charts_anonymous_user(self) -> None:
        request = self.factory.get('/')
        request.user = AnonymousUser()
        view = ReportView()
        view.request = request
        with self.assertRaises(TypeError):
            view.prepare_budget_charts(request)


class ReportsAnalyticMixinTest(TestCase):
    def test_get_context_report(self) -> None:
        mixin = ReportsAnalyticMixin()
        context = mixin.get_context_report()
        self.assertIsInstance(context, dict)
        self.assertEqual(len(context), 0)
