import json

from django.db.models import QuerySet, Sum
from django.db.models.functions import TruncMonth
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import ListView
from hasta_la_vista_money.budget.models import Planning
from hasta_la_vista_money.commonlogic.generate_dates import generate_date_list
from hasta_la_vista_money.custom_mixin import CustomNoPermissionMixin
from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.users.models import User


def get_queryset_budget_type_operation(model, user, category):
    """
    Получение Queryset по типу операции.

    :param model: Queryset
    :param user: User
    :param category: Queryset

    """
    return (
        model.objects.filter(
            user=user,
            category__parent_category=category,
        )
        .annotate(month=TruncMonth('date'))
        .values('month')
        .annotate(total_amount=Sum('amount'))
        .order_by('month')
    )


def category_amount_date_dict(
    model,
    parent_categories: QuerySet,
    user: User,
) -> dict:
    """
    Функция по формированию словаря с категориями и их суммой и датой.

    :param model: Queryset
    :param parent_categories: Queryset
    :param user: User

    :return: dict
    """
    result = {}
    for category in parent_categories:
        result[category.name] = {}
        queryset = get_queryset_budget_type_operation(model, user, category)
        for query_item in queryset:
            month_key = query_item['month'].strftime('%Y-%m')
            total_amount = query_item['total_amount']
            result[category.name][month_key] = total_amount
    return result


def category_amounts(
    list_dates: list,
    parent_categories: QuerySet,
    category_amount_date: dict,
    total_sum_list: list,
) -> list:
    """
    Функция формирующая список категорий и их сумм.

    :param list_dates: list
    :param parent_categories: Queryset
    :param category_amount_date: dict
    :param total_sum_list: list

    :return: list
    """
    category_amount = []

    for category in parent_categories:
        row = {'category': category.name, 'amounts': []}

        for date_index, date in enumerate(list_dates):
            month_key = date.date.strftime('%Y-%m')
            amount = category_amount_date.get(category.name, {}).get(
                month_key,
                '0,00',
            )
            row['amounts'].append(amount)
            amount_str = str(amount)
            total_sum_list[date_index] += float(amount_str.replace(',', '.'))

        category_amount.append(row)
    return category_amount


class BaseView:
    template_name = 'budget.html'


class BudgetView(CustomNoPermissionMixin, BaseView, ListView):
    model = Planning

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        user = get_object_or_404(User, username=self.request.user)

        list_dates = user.budget_date_list_users.order_by('date')
        total_sum_list_expense = [0] * len(list_dates)

        expense_model = Expense
        expense_parent_categories = user.category_expense_users.filter(
            parent_category=None,
        ).order_by('name')
        expenses_dict = category_amount_date_dict(
            expense_model,
            expense_parent_categories,
            user,
        )

        expense_category_amount = category_amounts(
            list_dates,
            expense_parent_categories,
            expenses_dict,
            total_sum_list_expense,
        )

        total_sum_list_income = [0] * len(list_dates)
        income_model = Income
        income_parent_categories = user.category_income_users.filter(
            parent_category=None,
        ).order_by('name')
        income_dict = category_amount_date_dict(
            income_model,
            income_parent_categories,
            user,
        )
        income_category_amount = category_amounts(
            list_dates,
            income_parent_categories,
            income_dict,
            total_sum_list_income,
        )

        context['list_dates'] = list_dates
        context['expense_category_amount'] = expense_category_amount
        context['income_category_amount'] = income_category_amount
        context['total_sum_list_expense'] = total_sum_list_expense
        context['total_sum_list_income'] = total_sum_list_income

        return context


def generate_date_list_view(request):
    """Функция представления генерации дат."""
    if request.method == 'POST':
        user = request.user
        queryset_user = get_object_or_404(User, username=user)
        queryset_last_date = queryset_user.budget_date_list_users.last().date
        generate_date_list(queryset_last_date, queryset_user)
        return redirect(reverse_lazy('budget:list'))


def change_planning(request):
    """Функция для изменения сумм планирования."""
    try:
        data = json.loads(request.body.decode('utf-8'))
        planning_value = data.get('planning')
        return JsonResponse({'planning_value': planning_value})
    except json.JSONDecodeError:
        return JsonResponse({'error': 'error'})
