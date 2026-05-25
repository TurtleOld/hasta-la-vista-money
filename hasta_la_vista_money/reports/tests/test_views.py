"""Tests for reports views."""

from typing import Any
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext

from hasta_la_vista_money.reports.views import ReportsAnalyticMixin, ReportView

User = get_user_model()


class ReportViewTest(TestCase):
    """Test cases for ReportView."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='reports_user',
            password='pass',  # nosec B106: test-only password
        )
        self.factory = RequestFactory()

    def test_get_method(self) -> None:
        self.client.force_login(self.user)
        with patch.object(ReportView, 'prepare_budget_charts') as mock_prepare:
            mock_prepare.return_value = {'test': 'data'}
            view = ReportView()
            view.request = self.factory.get('/')
            view.request.user = self.user
            response = view.get(view.request)
            self.assertEqual(response.status_code, 200)

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

        self.assertEqual(charts_data['selected_period'], 'y')
        self.assertEqual(charts_data['finances_url'], '/finance/')
        self.assertEqual(len(queries), 0)
        mock_budget_charts.assert_called_once_with(self.user, period='y')

    @patch('hasta_la_vista_money.reports.views.budget_charts')
    def test_prepare_budget_charts_passes_selected_period(
        self,
        mock_budget_charts: Any,
    ) -> None:
        request = self.factory.get('/?period=m')
        request.user = self.user
        view = ReportView()
        view.request = request
        mock_budget_charts.return_value = {}

        charts_data = view.prepare_budget_charts(request)

        self.assertEqual(charts_data['selected_period'], 'm')
        mock_budget_charts.assert_called_once_with(self.user, period='m')

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
