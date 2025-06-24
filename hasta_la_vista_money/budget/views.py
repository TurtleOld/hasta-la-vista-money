import json
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import ListView
from hasta_la_vista_money.budget.models import Planning, DateList
from hasta_la_vista_money.commonlogic.generate_dates import generate_date_list
from hasta_la_vista_money.custom_mixin import CustomNoPermissionMixin
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.users.models import User
from datetime import date
from decimal import Decimal
from collections import defaultdict
from django.db.models.functions import TruncMonth


def get_fact_amount(user, category, month, type_):
    if type_ == 'expense':
        return (
            Expense.objects.filter(
                user=user,
                category=category,
                date__year=month.year,
                date__month=month.month,
            ).aggregate(total=Sum('amount'))['total']
            or 0
        )
    else:
        return (
            Income.objects.filter(
                user=user,
                category=category,
                date__year=month.year,
                date__month=month.month,
            ).aggregate(total=Sum('amount'))['total']
            or 0
        )


def get_plan_amount(user, category, month, type_):
    q = Planning.objects.filter(
        user=user,
        date=month,
        type=type_,
    )
    if type_ == 'expense':
        q = q.filter(category_expense=category)
    else:
        q = q.filter(category_income=category)
    plan = q.first()
    return plan.amount if plan else 0


def get_categories(user, type_):
    if type_ == 'expense':
        return user.category_expense_users.filter(parent_category=None).order_by('name')
    else:
        return user.category_income_users.filter(parent_category=None).order_by('name')


class BaseView:
    template_name = 'budget.html'


class BudgetView(CustomNoPermissionMixin, BaseView, ListView):
    model = Planning
    template_name = "budget/budget.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = get_object_or_404(User, username=self.request.user)
        list_dates = DateList.objects.filter(user=user).order_by('date')
        months = [d.date for d in list_dates]

        # Получаем все категории
        expense_categories = list(get_categories(user, 'expense'))
        income_categories = list(get_categories(user, 'income'))

        # ----------- Расходы -----------
        # Все расходы за нужные месяцы и категории одним запросом, группировка по месяцу
        if months:
            expenses = (
                Expense.objects.filter(
                    user=user,
                    category__in=expense_categories,
                    date__gte=months[0],
                    date__lte=months[-1],
                )
                .annotate(month=TruncMonth("date"))
                .values("category_id", "month")
                .annotate(total=Sum("amount"))
            )
        else:
            expenses = []
        expense_fact_map = defaultdict(lambda: defaultdict(lambda: 0))
        for e in expenses:
            month_date = (
                e["month"].date() if hasattr(e["month"], "date") else e["month"]
            )
            expense_fact_map[e["category_id"]][month_date] = e["total"] or 0

        plans_exp = Planning.objects.filter(
            user=user,
            date__in=months,
            type='expense',
            category_expense__in=expense_categories,
        ).values('category_expense_id', 'date', 'amount')
        expense_plan_map = defaultdict(lambda: defaultdict(lambda: 0))
        for p in plans_exp:
            expense_plan_map[p['category_expense_id']][p['date']] = p['amount'] or 0

        expense_data = []
        total_fact_expense = [0] * len(months)
        total_plan_expense = [0] * len(months)
        for cat in expense_categories:
            row = {
                'category': cat.name,
                'category_id': cat.id,
                'fact': [],
                'plan': [],
                'diff': [],
                'percent': [],
            }
            for i, m in enumerate(months):
                fact = expense_fact_map[cat.id][m]
                plan = expense_plan_map[cat.id][m]
                diff = fact - plan
                percent = (fact / plan * 100) if plan else None
                row['fact'].append(fact)
                row['plan'].append(plan)
                row['diff'].append(diff)
                row['percent'].append(percent)
                total_fact_expense[i] += fact
                total_plan_expense[i] += plan
            expense_data.append(row)

        if months:
            incomes = (
                Income.objects.filter(
                    user=user,
                    category__in=income_categories,
                    date__gte=months[0],
                    date__lte=months[-1],
                )
                .annotate(month=TruncMonth("date"))
                .values("category_id", "month")
                .annotate(total=Sum("amount"))
            )
        else:
            incomes = []
        income_fact_map = defaultdict(lambda: defaultdict(lambda: 0))
        for e in incomes:
            month_date = (
                e["month"].date() if hasattr(e["month"], "date") else e["month"]
            )
            income_fact_map[e["category_id"]][month_date] = e["total"] or 0

        plans_inc = Planning.objects.filter(
            user=user,
            date__in=months,
            type='income',
            category_income__in=income_categories,
        ).values('category_income_id', 'date', 'amount')
        income_plan_map = defaultdict(lambda: defaultdict(lambda: 0))
        for p in plans_inc:
            income_plan_map[p['category_income_id']][p['date']] = p['amount'] or 0

        income_data = []
        total_fact_income = [0] * len(months)
        total_plan_income = [0] * len(months)
        for cat in income_categories:
            row = {
                'category': cat.name,
                'category_id': cat.id,
                'fact': [],
                'plan': [],
                'diff': [],
                'percent': [],
            }
            for i, m in enumerate(months):
                fact = income_fact_map[cat.id][m]
                plan = income_plan_map[cat.id][m]
                diff = fact - plan
                percent = (fact / plan * 100) if plan else None
                row['fact'].append(fact)
                row['plan'].append(plan)
                row['diff'].append(diff)
                row['percent'].append(percent)
                total_fact_income[i] += fact
                total_plan_income[i] += plan
            income_data.append(row)
        context['months'] = months
        context['expense_data'] = expense_data
        context['income_data'] = income_data
        context['total_fact_expense'] = total_fact_expense
        context['total_plan_expense'] = total_plan_expense
        context['total_fact_income'] = total_fact_income
        context['total_plan_income'] = total_plan_income
        return context


def generate_date_list_view(request):
    """Функция представления генерации дат."""
    if request.method == 'POST':
        user = request.user
        queryset_user = get_object_or_404(User, username=user)
        last_date_obj = queryset_user.budget_date_list_users.last()
        if last_date_obj:
            queryset_last_date = last_date_obj.date
        else:
            queryset_last_date = date.today().replace(day=1)
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


def save_planning(request):
    print('save_planning called', request.body)
    """AJAX: сохранить план по категории, месяцу, типу (расход/доход)"""
    if (
        request.method == 'POST'
        and request.headers.get('x-requested-with') == 'XMLHttpRequest'
    ):
        data = json.loads(request.body.decode('utf-8'))
        user = request.user
        month = date.fromisoformat(data['month'])
        try:
            amount = Decimal(str(data['amount']))
        except Exception:
            amount = Decimal('0')
        type_ = data['type']
        if type_ == 'expense':
            category = get_object_or_404(ExpenseCategory, id=data['category_id'])
            plan, created = Planning.objects.get_or_create(
                user=user,
                category_expense=category,
                date=month,
                type=type_,
                defaults={'amount': amount},
            )
        else:
            category = get_object_or_404(IncomeCategory, id=data['category_id'])
            plan, created = Planning.objects.get_or_create(
                user=user,
                category_income=category,
                date=month,
                type=type_,
                defaults={'amount': amount},
            )
        if not created:
            plan.amount = amount
            plan.save()
        return JsonResponse({'success': True, 'amount': str(plan.amount)})
    return JsonResponse({'success': False, 'error': 'Invalid request'})
