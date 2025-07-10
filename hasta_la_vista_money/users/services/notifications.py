from typing import List, Dict
from django.utils import timezone
from django.db.models import Sum
from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import User


def get_user_notifications(user: User) -> List[Dict[str, str]]:
    today = timezone.now().date()
    month_start = today.replace(day=1)
    notifications = []
    accounts = Account.objects.filter(user=user)
    low_balance_accounts = [acc for acc in accounts if float(acc.balance) < 1000]
    if low_balance_accounts:
        notifications.append(
            {
                'type': 'warning',
                'title': 'Низкий баланс на счетах',
                'message': f'На следующих счетах низкий баланс: {", ".join([acc.name_account for acc in low_balance_accounts])}',
                'icon': 'bi-exclamation-triangle',
            }
        )
    current_month_expenses = (
        Expense.objects.filter(user=user, date__gte=month_start).aggregate(
            total=Sum('amount'),
        )['total']
        or 0
    )
    current_month_income = (
        Income.objects.filter(user=user, date__gte=month_start).aggregate(
            total=Sum('amount'),
        )['total']
        or 0
    )
    if current_month_expenses > current_month_income:
        notifications.append(
            {
                'type': 'danger',
                'title': 'Превышение расходов',
                'message': f'В текущем месяце расходы превышают доходы на {current_month_expenses - current_month_income:.2f} ₽',
                'icon': 'bi-arrow-down-circle',
            }
        )
    if (
        current_month_income > 0
        and (current_month_income - current_month_expenses) / current_month_income > 0.2
    ):
        notifications.append(
            {
                'type': 'success',
                'title': 'Отличные сбережения',
                'message': 'Вы сэкономили более 20% от доходов в текущем месяце',
                'icon': 'bi-check-circle',
            }
        )
    return notifications
