from typing import Any, Dict
from django.db.models import Sum
from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.users.models import User


def get_user_export_data(user: User) -> Dict[str, Any]:
    return {
        'user_info': {
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'date_joined': user.date_joined.isoformat(),
            'last_login': user.last_login.isoformat() if user.last_login else None,
        },
        'accounts': list(
            Account.objects.filter(user=user).values(
                'name_account', 'balance', 'currency', 'created_at'
            )
        ),
        'expenses': list(
            Expense.objects.filter(user=user).values(
                'amount', 'date', 'category__name', 'account__name_account'
            )
        ),
        'incomes': list(
            Income.objects.filter(user=user).values(
                'amount', 'date', 'category__name', 'account__name_account'
            )
        ),
        'receipts': list(
            Receipt.objects.filter(user=user).values(
                'receipt_date', 'seller__name_seller', 'total_sum'
            )
        ),
        'statistics': {
            'total_balance': float(
                Account.objects.filter(user=user).aggregate(total=Sum('balance'))[
                    'total'
                ]
                or 0
            ),
            'total_expenses': float(
                Expense.objects.filter(user=user).aggregate(total=Sum('amount'))[
                    'total'
                ]
                or 0
            ),
            'total_incomes': float(
                Income.objects.filter(user=user).aggregate(total=Sum('amount'))['total']
                or 0
            ),
            'receipts_count': Receipt.objects.filter(user=user).count(),
        },
    }
