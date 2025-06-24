from collections import defaultdict
from decimal import Decimal

from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Sum
from django.shortcuts import render, get_object_or_404
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django.views.generic import TemplateView
from hasta_la_vista_money.custom_mixin import CustomNoPermissionMixin
from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.budget.models import DateList
from hasta_la_vista_money.users.models import User
from django.db.models.functions import TruncMonth


class ReportView(CustomNoPermissionMixin, SuccessMessageMixin, TemplateView):
    template_name = 'reports/reports.html'
    no_permission_url = reverse_lazy('login')
    success_url = reverse_lazy('reports:list')

    @classmethod
    def collect_datasets(cls, request):
        expense_dataset = (
            Expense.objects.filter(
                user=request.user,
            )
            .values(
                'date',
            )
            .annotate(
                total_amount=Sum('amount'),
            )
            .order_by('date')
        )

        income_dataset = (
            Income.objects.filter(
                user=request.user,
            )
            .values(
                'date',
            )
            .annotate(
                total_amount=Sum('amount'),
            )
            .order_by('date')
        )

        return expense_dataset, income_dataset

    @classmethod
    def transform_data(cls, dataset):
        dates = []
        amounts = []

        for date_amount in dataset:
            dates.append(
                date_amount['date'].strftime('%Y-%m-%d'),
            )
            amounts.append(float(date_amount['total_amount']))

        return dates, amounts

    @classmethod
    def transform_data_expense(cls, expense_dataset):
        return cls.transform_data(expense_dataset)

    @classmethod
    def transform_data_income(cls, income_dataset):
        return cls.transform_data(income_dataset)

    @classmethod
    def unique_data(cls, dates, amounts):
        unique_dates = []
        unique_amounts = []

        for data_index, date in enumerate(dates):
            if date not in unique_dates:
                unique_dates.append(date)
                unique_amounts.append(amounts[data_index])
            else:
                index = unique_dates.index(date)
                unique_amounts[index] += amounts[index]

        return unique_dates, unique_amounts

    @classmethod
    def unique_expense_data(cls, expense_dates, expense_amounts):
        return cls.unique_data(expense_dates, expense_amounts)

    @classmethod
    def unique_income_data(cls, income_dates, income_amounts):
        return cls.unique_data(income_dates, income_amounts)

    @classmethod
    def pie_expense_category(cls, request):
        expense_data = defaultdict(lambda: defaultdict(float))
        subcategory_data = defaultdict(list)

        for expense in Expense.objects.filter(user=request.user).all():
            parent_category_name = (
                expense.category.parent_category.name
                if expense.category.parent_category
                else expense.category.name
            )
            month = expense.date.strftime('%B %Y')
            expense_amount = float(expense.amount)
            expense_data[parent_category_name][month] += expense_amount

            # Collect subcategory data
            if expense.category.parent_category:
                parent_month_key = f'{parent_category_name}_{month}'
                subcategory_name = expense.category.name
                subcategory_amount = expense_amount
                subcategory_data[parent_month_key].append(
                    {'name': subcategory_name, 'y': subcategory_amount},
                )

        charts_data = []

        for parent_category, subcategories in expense_data.items():
            data = [
                {
                    'name': month,
                    'y': amount,
                    'drilldown': f'{parent_category}_{month}',
                }
                for month, amount in subcategories.items()
            ]
            drilldown_series = [
                {
                    'id': f'{parent_category}_{month}',
                    'name': f'Subcategories for {parent_category} in {month}',
                    'data': subcategory_data[f'{parent_category}_{month}'],
                }
                for month in subcategories.keys()
            ]
            chart_data = {
                'chart': {'type': 'pie'},
                'title': {
                    'text': _(f'Статистика расходов по категории {parent_category}'),
                },
                'series': [{'name': parent_category, 'data': data}],
                'credits': {'enabled': 'false'},
                'exporting': {'enabled': 'false'},
                'drilldown': {
                    'series': drilldown_series,
                },
            }
            charts_data.append(chart_data)

        return charts_data

    def get(self, request, *args, **kwargs):
        # Подготовка данных для новых графиков бюджета
        budget_chart_data = self.prepare_budget_charts(request)
        return render(
            request,
            self.template_name,
            budget_chart_data,
        )

    def prepare_budget_charts(self, request):
        """Подготовка данных для графиков бюджета"""
        user = get_object_or_404(User, username=request.user)
        list_dates = DateList.objects.filter(user=user).order_by('date')
        months = [d.date for d in list_dates]

        expense_categories = list(
            user.category_expense_users.filter(parent_category=None).order_by('name')
        )
        income_categories = list(
            user.category_income_users.filter(parent_category=None).order_by('name')
        )

        chart_labels = [m.strftime('%b %Y') for m in months]

        total_fact_income = [0] * len(months)
        total_fact_expense = [0] * len(months)

        if months:
            expenses = (
                Expense.objects.filter(
                    user=user,
                    category__in=expense_categories,
                    date__gte=months[0],
                    date__lte=months[-1],
                )
                .annotate(month=TruncMonth('date'))
                .values('category_id', 'month')
                .annotate(total=Sum('amount'))
            )
            expense_fact_map = defaultdict(lambda: defaultdict(lambda: 0))
            for e in expenses:
                month_date = (
                    e['month'].date() if hasattr(e['month'], 'date') else e['month']
                )
                expense_fact_map[e['category_id']][month_date] = e['total'] or 0

            for i, m in enumerate(months):
                for cat in expense_categories:
                    total_fact_expense[i] += expense_fact_map[cat.id][m]

            incomes = (
                Income.objects.filter(
                    user=user,
                    category__in=income_categories,
                    date__gte=months[0],
                    date__lte=months[-1],
                )
                .annotate(month=TruncMonth('date'))
                .values('category_id', 'month')
                .annotate(total=Sum('amount'))
            )
            income_fact_map = defaultdict(lambda: defaultdict(lambda: 0))
            for e in incomes:
                month_date = (
                    e['month'].date() if hasattr(e['month'], 'date') else e['month']
                )
                income_fact_map[e['category_id']][month_date] = e['total'] or 0

            for i, m in enumerate(months):
                for cat in income_categories:
                    total_fact_income[i] += income_fact_map[cat.id][m]

        chart_balance = []
        for i in range(len(months)):
            balance = total_fact_income[i] - total_fact_expense[i]
            chart_balance.append(float(balance))

        pie_labels = []
        pie_values = []
        if months and expense_categories:
            category_totals = defaultdict(lambda: Decimal('0'))
            for cat in expense_categories:
                for month in months:
                    amount = expense_fact_map[cat.id][month]
                    if amount:
                        category_totals[cat.id] += amount

            for cat in expense_categories:
                total = category_totals[cat.id]
                if total > 0:
                    pie_labels.append(cat.name)
                    pie_values.append(float(total))

        return {
            'chart_labels': chart_labels,
            'chart_income': total_fact_income,
            'chart_expense': total_fact_expense,
            'chart_balance': chart_balance,
            'pie_labels': pie_labels,
            'pie_values': pie_values,
        }


class ReportsAnalyticMixin(TemplateView):
    def get_context_report(self, request, *args, **kwargs):
        return
