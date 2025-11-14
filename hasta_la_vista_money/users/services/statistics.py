from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone
from typing_extensions import TypedDict

from hasta_la_vista_money import constants
from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.users.models import User


class UserStatistics(TypedDict, total=False):
    """Статистика пользователя."""

    total_balance: Decimal
    accounts_count: int
    current_month_expenses: Decimal
    current_month_income: Decimal
    last_month_expenses: Decimal
    last_month_income: Decimal
    recent_expenses: list[Expense]
    recent_incomes: list[Income]
    receipts_count: int
    top_expense_categories: list[dict[str, str | Decimal]]
    monthly_savings: Decimal
    last_month_savings: Decimal


def get_user_statistics(user: User) -> UserStatistics:
    today = timezone.now().date()
    month_start = today.replace(day=1)
    last_month = (month_start - timedelta(days=1)).replace(day=1)

    month_start_dt = timezone.make_aware(
        datetime.combine(month_start, time.min)
    )
    last_month_dt = timezone.make_aware(datetime.combine(last_month, time.min))

    accounts_qs = Account.objects.filter(user=user)
    accounts_data = accounts_qs.aggregate(
        total_balance=Sum('balance'),
        accounts_count=Count('id'),
    )
    total_balance = accounts_data['total_balance'] or constants.ZERO
    accounts_count = accounts_data['accounts_count'] or constants.ZERO

    current_month_expenses = (
        Expense.objects.filter(user=user, date__gte=month_start_dt).aggregate(
            total=Sum('amount'),
        )['total']
        or constants.ZERO
    )
    current_month_income = (
        Income.objects.filter(user=user, date__gte=month_start_dt).aggregate(
            total=Sum('amount'),
        )['total']
        or constants.ZERO
    )

    last_month_expenses = (
        Expense.objects.filter(
            user=user,
            date__gte=last_month_dt,
            date__lt=month_start_dt,
        ).aggregate(total=Sum('amount'))['total']
        or constants.ZERO
    )
    last_month_income = (
        Income.objects.filter(
            user=user,
            date__gte=last_month_dt,
            date__lt=month_start_dt,
        ).aggregate(total=Sum('amount'))['total']
        or constants.ZERO
    )

    recent_expenses = (
        Expense.objects.filter(user=user)
        .select_related('category', 'account')
        .order_by('-date')[: constants.RECENT_ITEMS_LIMIT]
    )
    recent_incomes = (
        Income.objects.filter(user=user)
        .select_related('category', 'account')
        .order_by('-date')[: constants.RECENT_ITEMS_LIMIT]
    )

    receipts_count = Receipt.objects.filter(user=user).count()

    top_expense_categories = (
        Expense.objects.filter(user=user, date__gte=month_start_dt)
        .values('category__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')[: constants.RECENT_ITEMS_LIMIT]
    )

    return {
        'total_balance': Decimal(str(total_balance)),
        'accounts_count': int(accounts_count),
        'current_month_expenses': Decimal(str(current_month_expenses)),
        'current_month_income': Decimal(str(current_month_income)),
        'last_month_expenses': Decimal(str(last_month_expenses)),
        'last_month_income': Decimal(str(last_month_income)),
        'recent_expenses': list(recent_expenses),
        'recent_incomes': list(recent_incomes),
        'receipts_count': receipts_count,
        'top_expense_categories': list(top_expense_categories),
        'monthly_savings': Decimal(
            str(current_month_income - current_month_expenses),
        ),
        'last_month_savings': Decimal(
            str(last_month_income - last_month_expenses),
        ),
    }
