import json
from collections import defaultdict

from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Sum
from django.shortcuts import render
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django.views.generic import TemplateView
from hasta_la_vista_money.custom_mixin import CustomNoPermissionMixin
from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.income.models import Income


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
        expense_dataset, income_dataset = self.collect_datasets(request)

        expense_dates, expense_amounts = self.transform_data_expense(
            expense_dataset,
        )
        income_dates, income_amounts = self.transform_data_income(
            income_dataset,
        )

        unique_expense_dates, unique_expense_amounts = self.unique_expense_data(
            expense_dates,
            expense_amounts,
        )

        unique_income_dates, unique_income_amounts = self.unique_income_data(
            income_dates,
            income_amounts,
        )

        charts_data = self.pie_expense_category(request)

        chart_expense = {
            'chart': {'type': 'line'},
            'title': {'text': _('Статистика по расходам')},
            'xAxis': [
                {
                    'categories': unique_expense_dates,
                    'title': {'text': _('Дата')},
                },
            ],
            'yAxis': {'title': {'text': _('Сумма')}},
            'series': [
                {
                    'name': _('Расходы'),
                    'data': unique_expense_amounts,
                    'color': 'red',
                    'xAxis': 0,
                },
            ],
            'credits': {
                'enabled': False,
            },
            'exporting': {
                'enabled': False,
            },
        }

        chart_income = {
            'chart': {'type': 'line'},
            'title': {'text': _('Статистика по доходам')},
            'xAxis': [
                {
                    'categories': unique_income_dates,
                    'title': {'text': _('Дата')},
                },
            ],
            'yAxis': {'title': {'text': _('Сумма')}},
            'series': [
                {
                    'name': _('Доходы'),
                    'data': unique_income_amounts,
                    'color': 'green',
                    'xAxis': 0,
                },
            ],
            'credits': {
                'enabled': False,
            },
            'exporting': {
                'enabled': False,
            },
        }

        dump_expense = json.dumps(chart_expense)
        dump_income = json.dumps(chart_income)
        return render(
            request,
            self.template_name,
            {
                'chart_expense': dump_expense,
                'chart_income': dump_income,
                'charts_data': charts_data,
            },
        )


class ReportsAnalyticMixin(TemplateView):
    def get_context_report(self, request, *args, **kwargs):
        return
