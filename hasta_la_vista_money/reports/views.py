from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, cast

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django.views.generic import TemplateView

from hasta_la_vista_money.reports.services.aggregation import (
    budget_charts,
    collect_datasets,
    transform_dataset,
    unique_aggregate,
)
from hasta_la_vista_money.reports.services.aggregation import (
    pie_expense_category as pie_expense_category_service,
)
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User


class ReportView(LoginRequiredMixin, SuccessMessageMixin[Any], TemplateView):
    template_name = 'reports/reports.html'
    no_permission_url = reverse_lazy('login')
    success_url = reverse_lazy('reports:list')

    @classmethod
    def collect_datasets(cls, request: HttpRequest) -> tuple[Any, Any]:
        if isinstance(request.user, AnonymousUser):
            raise TypeError('User must be authenticated')
        if not isinstance(request.user, User):
            raise TypeError('User must be authenticated')
        return collect_datasets(request.user)

    @classmethod
    def transform_data(cls, dataset: Any) -> tuple[list[str], list[float]]:
        return transform_dataset(dataset)

    @classmethod
    def transform_data_expense(
        cls,
        expense_dataset: Any,
    ) -> tuple[list[str], list[float]]:
        return cls.transform_data(expense_dataset)

    @classmethod
    def transform_data_income(
        cls,
        income_dataset: Any,
    ) -> tuple[list[str], list[float]]:
        return cls.transform_data(income_dataset)

    @classmethod
    def unique_data(
        cls,
        dates: list[str],
        amounts: list[float],
    ) -> tuple[list[str], list[float]]:
        return unique_aggregate(dates, amounts)

    @classmethod
    def unique_expense_data(
        cls,
        expense_dates: list[str],
        expense_amounts: list[float],
    ) -> tuple[list[str], list[float]]:
        return cls.unique_data(expense_dates, expense_amounts)

    @classmethod
    def unique_income_data(
        cls,
        income_dates: list[str],
        income_amounts: list[float],
    ) -> tuple[list[str], list[float]]:
        return cls.unique_data(income_dates, income_amounts)

    @classmethod
    def pie_expense_category(cls, request: HttpRequest) -> list[dict[str, Any]]:
        if isinstance(request.user, AnonymousUser):
            raise TypeError('User must be authenticated')
        if not isinstance(request.user, User):
            raise TypeError('User must be authenticated')
        charts = pie_expense_category_service(request.user)
        charts_data = []
        for ch in charts:
            parent_category = ch['parent_category']
            chart_data = {
                'chart': {'type': 'pie'},
                'title': {
                    'text': _(
                        f'Статистика расходов по категории {parent_category}',
                    ),
                },
                'series': [{'name': parent_category, 'data': ch['data']}],
                'credits': {'enabled': 'false'},
                'exporting': {'enabled': 'false'},
                'drilldown': {'series': ch['drilldown_series']},
            }
            charts_data.append(chart_data)
        return charts_data

    def get(self, request: HttpRequest) -> HttpResponse:
        budget_chart_data = self.prepare_budget_charts(request)
        template_name = self.template_name
        if template_name is None:
            raise ValueError('template_name must be set')
        return render(
            request,
            template_name,
            budget_chart_data,
        )

    def _aggregate_for_type(
        self,
        user: User,
        categories: list[Category],
        months: list[date],
        type_value: str,
    ) -> dict[int, dict[date, Decimal | int]]:
        fact_map: dict[int, dict[date, Decimal | int]] = defaultdict(
            lambda: defaultdict(lambda: 0),
        )
        if not months:
            return fact_map

        rows = (
            Transaction.objects.filter(
                user=user,
                type=type_value,
                category__in=categories,
                date__gte=months[0],
                date__lte=months[-1],
            )
            .annotate(month=TruncMonth('date'))
            .values('category_id', 'month')
            .annotate(total=Sum('amount'))
        )
        for row in rows:
            month_date = (
                row['month'].date()
                if hasattr(row['month'], 'date')
                else row['month']
            )
            total_amount = row['total'] if row['total'] is not None else 0
            fact_map[row['category_id']][month_date] = total_amount
        return fact_map

    def _get_expense_data(
        self,
        user: User,
        categories: list[Category],
        months: list[date],
    ) -> dict[int, dict[date, Decimal | int]]:
        """Aggregate expense transactions per category and month."""
        return self._aggregate_for_type(
            user,
            categories,
            months,
            TransactionType.EXPENSE,
        )

    def _get_income_data(
        self,
        user: User,
        categories: list[Category],
        months: list[date],
    ) -> dict[int, dict[date, Decimal | int]]:
        """Aggregate income transactions per category and month."""
        return self._aggregate_for_type(
            user,
            categories,
            months,
            TransactionType.INCOME,
        )

    def _calculate_totals(
        self,
        categories: list[Category],
        months: list[date],
        fact_map: dict[int, dict[date, Decimal | int]],
    ) -> list[int]:
        """Calculate total amounts by month."""
        totals: list[int] = [0] * len(months)
        for i, m in enumerate(months):
            for cat in categories:
                value = fact_map[cat.pk][m]
                totals[i] += int(value) if isinstance(value, Decimal) else value
        return totals

    def _calculate_category_totals(
        self,
        categories: list[Category],
        months: list[date],
        fact_map: dict[int, dict[date, Decimal | int]],
    ) -> dict[int, Decimal]:
        """Calculate total amounts by category."""
        category_totals: dict[int, Decimal] = defaultdict(lambda: Decimal(0))
        for cat in categories:
            for month in months:
                amount = fact_map[cat.pk][month]
                if amount:
                    category_totals[cat.pk] += amount
        return category_totals

    def _calculate_pie_data(
        self,
        categories: list[Category],
        months: list[date],
        fact_map: dict[int, dict[date, Decimal | int]],
    ) -> tuple[list[str], list[float]]:
        """Calculate data for pie chart."""
        labels: list[str] = []
        values: list[float] = []
        if not months or not categories:
            return labels, values

        category_totals = self._calculate_category_totals(
            categories,
            months,
            fact_map,
        )

        for cat in categories:
            total = category_totals[cat.pk]
            if total > 0:
                labels.append(cat.name)
                values.append(float(total))
        return labels, values

    def prepare_budget_charts(self, request: HttpRequest) -> dict[str, Any]:
        """Prepare budget chart data."""
        if isinstance(request.user, AnonymousUser):
            raise TypeError('User must be authenticated')
        charts_data = budget_charts(
            cast('User', request.user),
        )
        return cast('dict[str, Any]', charts_data)


class ReportsAnalyticMixin(TemplateView):
    def get_context_report(self) -> dict[str, Any]:
        return {}
