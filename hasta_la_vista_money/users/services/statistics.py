from typing import Any, Dict
from django.db.models import Sum, Count
from django.utils import timezone
from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.users.models import User


def get_user_statistics(user: User) -> Dict[str, Any]:
    today = timezone.now().date()
    month_start = today.replace(day=1)
    last_month = (month_start - timezone.timedelta(days=1)).replace(day=1)

    accounts_qs = Account.objects.filter(user=user)
    accounts_data = accounts_qs.aggregate(
        total_balance=Sum('balance'),
        accounts_count=Count('id'),
    )
    total_balance = accounts_data['total_balance'] or 0
    accounts_count = accounts_data['accounts_count'] or 0

    current_month_expenses = (
        Expense.objects.filter(user=user, date__gte=month_start).aggregate(
            total=Sum('amount')
        )['total']
        or 0
    )
    current_month_income = (
        Income.objects.filter(user=user, date__gte=month_start).aggregate(
            total=Sum('amount')
        )['total']
        or 0
    )

    last_month_expenses = (
        Expense.objects.filter(
            user=user, date__gte=last_month, date__lt=month_start
        ).aggregate(total=Sum('amount'))['total']
        or 0
    )
    last_month_income = (
        Income.objects.filter(
            user=user, date__gte=last_month, date__lt=month_start
        ).aggregate(total=Sum('amount'))['total']
        or 0
    )

    recent_expenses = (
        Expense.objects.filter(user=user)
        .select_related('category', 'account')
        .order_by('-date')[:5]
    )
    recent_incomes = (
        Income.objects.filter(user=user)
        .select_related('category', 'account')
        .order_by('-date')[:5]
    )

    receipts_count = Receipt.objects.filter(user=user).count()

    top_expense_categories = (
        Expense.objects.filter(user=user, date__gte=month_start)
        .values('category__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')[:5]
    )

    return {
        'total_balance': total_balance,
        'accounts_count': accounts_count,
        'current_month_expenses': current_month_expenses,
        'current_month_income': current_month_income,
        'last_month_expenses': last_month_expenses,
        'last_month_income': last_month_income,
        'recent_expenses': list(recent_expenses),
        'recent_incomes': list(recent_incomes),
        'receipts_count': receipts_count,
        'top_expense_categories': list(top_expense_categories),
        'monthly_savings': current_month_income - current_month_expenses,
        'last_month_savings': last_month_income - last_month_expenses,
    }
