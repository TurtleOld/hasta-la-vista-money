from collections import defaultdict
from decimal import Decimal
from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django.views.generic import TemplateView

from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.reports.services.aggregation import (
    budget_charts,
    collect_datasets,
    transform_dataset,
    unique_aggregate,
)
from hasta_la_vista_money.reports.services.aggregation import (
    pie_expense_category as pie_expense_category_service,
)
from hasta_la_vista_money.users.models import User


class ReportView(LoginRequiredMixin, SuccessMessageMixin, TemplateView):
    template_name = 'reports/reports.html'
    no_permission_url = reverse_lazy('login')
    success_url = reverse_lazy('reports:list')

    @classmethod
    def collect_datasets(cls, request):
        return collect_datasets(request.user)

    @classmethod
    def transform_data(cls, dataset):
        return transform_dataset(dataset)

    @classmethod
    def transform_data_expense(cls, expense_dataset):
        return cls.transform_data(expense_dataset)

    @classmethod
    def transform_data_income(cls, income_dataset):
        return cls.transform_data(income_dataset)

    @classmethod
    def unique_data(cls, dates, amounts):
        return unique_aggregate(dates, amounts)

    @classmethod
    def unique_expense_data(cls, expense_dates, expense_amounts):
        return cls.unique_data(expense_dates, expense_amounts)

    @classmethod
    def unique_income_data(cls, income_dates, income_amounts):
        return cls.unique_data(income_dates, income_amounts)

    @classmethod
    def pie_expense_category(cls, request):
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
            template_name = 'reports/reports.html'
        return render(
            request,
            template_name,
            budget_chart_data,
        )

    def _get_expense_data(self, user, categories, months):
        """Получить данные о расходах по категориям и месяцам."""
        fact_map = defaultdict(lambda: defaultdict(lambda: 0))
        if not months:
            return fact_map

        expenses = (
            Expense.objects.filter(
                user=user,
                category__in=categories,
                date__gte=months[0],
                date__lte=months[-1],
            )
            .annotate(month=TruncMonth('date'))
            .values('category_id', 'month')
            .annotate(total=Sum('amount'))
        )
        for e in expenses:
            month_date = (
                e['month'].date() if hasattr(e['month'], 'date') else e['month']
            )
            total_amount = e['total'] if e['total'] is not None else 0
            fact_map[e['category_id']][month_date] = total_amount
        return fact_map

    def _get_income_data(self, user, categories, months):
        """Получить данные о доходах по категориям и месяцам."""
        fact_map = defaultdict(lambda: defaultdict(lambda: 0))
        if not months:
            return fact_map

        incomes = (
            Income.objects.filter(
                user=user,
                category__in=categories,
                date__gte=months[0],
                date__lte=months[-1],
            )
            .annotate(month=TruncMonth('date'))
            .values('category_id', 'month')
            .annotate(total=Sum('amount'))
        )
        for e in incomes:
            month_date = (
                e['month'].date() if hasattr(e['month'], 'date') else e['month']
            )
            total_amount = e['total'] if e['total'] is not None else 0
            fact_map[e['category_id']][month_date] = total_amount
        return fact_map

    def _calculate_totals(self, categories, months, fact_map):
        """Рассчитать общие суммы по месяцам."""
        totals = [0] * len(months)
        for i, m in enumerate(months):
            for cat in categories:
                totals[i] += fact_map[cat.id][m]
        return totals

    def _calculate_category_totals(self, categories, months, fact_map):
        """Рассчитать общие суммы по категориям."""
        category_totals = defaultdict(lambda: Decimal(0))
        for cat in categories:
            for month in months:
                amount = fact_map[cat.id][month]
                if amount:
                    category_totals[cat.id] += amount
        return category_totals

    def _calculate_pie_data(self, categories, months, fact_map):
        """Рассчитать данные для круговой диаграммы."""
        labels = []
        values = []
        if not months or not categories:
            return labels, values

        category_totals = self._calculate_category_totals(
            categories,
            months,
            fact_map,
        )

        for cat in categories:
            total = category_totals[cat.id]
            if total > 0:
                labels.append(cat.name)
                values.append(float(total))
        return labels, values

    def prepare_budget_charts(self, request):
        """Подготовка данных для графиков бюджета."""
        return budget_charts(get_object_or_404(User, username=request.user))


class ReportsAnalyticMixin(TemplateView):
    def get_context_report(self) -> dict[str, Any]:
        return
