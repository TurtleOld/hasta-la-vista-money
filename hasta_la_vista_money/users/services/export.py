from datetime import datetime
from decimal import Decimal
from typing import cast

from django.db.models import Sum
from typing_extensions import TypedDict

from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.users.models import User


class UserInfoDict(TypedDict):
    """Информация о пользователе для экспорта."""

    username: str
    email: str
    first_name: str
    last_name: str
    date_joined: str
    last_login: str | None


class StatisticsDict(TypedDict):
    """Статистика для экспорта."""

    total_balance: float
    total_expenses: float
    total_incomes: float
    receipts_count: int


class AccountDict(TypedDict):
    """Словарь с данными счета."""

    name_account: str
    balance: Decimal
    currency: str
    created_at: datetime | None


class ExpenseDict(TypedDict):
    """Словарь с данными расхода."""

    amount: Decimal
    date: datetime
    category__name: str
    account__name_account: str


class IncomeDict(TypedDict):
    """Словарь с данными дохода."""

    amount: Decimal
    date: datetime
    category__name: str
    account__name_account: str


class ReceiptDict(TypedDict):
    """Словарь с данными чека."""

    receipt_date: datetime
    seller__name_seller: str
    total_sum: Decimal


class UserExportData(TypedDict):
    """Данные для экспорта пользователя."""

    user_info: UserInfoDict
    accounts: list[AccountDict]
    expenses: list[ExpenseDict]
    incomes: list[IncomeDict]
    receipts: list[ReceiptDict]
    statistics: StatisticsDict


def get_user_export_data(user: User) -> UserExportData:
    return {
        'user_info': {
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'date_joined': user.date_joined.isoformat(),
            'last_login': user.last_login.isoformat()
            if user.last_login
            else None,
        },
        'accounts': cast(
            'list[AccountDict]',
            list(
                Account.objects.filter(user=user).values(
                    'name_account',
                    'balance',
                    'currency',
                    'created_at',
                ),
            ),
        ),
        'expenses': cast(
            'list[ExpenseDict]',
            list(
                Expense.objects.filter(user=user).values(
                    'amount',
                    'date',
                    'category__name',
                    'account__name_account',
                ),
            ),
        ),
        'incomes': cast(
            'list[IncomeDict]',
            list(
                Income.objects.filter(user=user).values(
                    'amount',
                    'date',
                    'category__name',
                    'account__name_account',
                ),
            ),
        ),
        'receipts': cast(
            'list[ReceiptDict]',
            list(
                Receipt.objects.filter(user=user).values(
                    'receipt_date',
                    'seller__name_seller',
                    'total_sum',
                ),
            ),
        ),
        'statistics': {
            'total_balance': float(
                Account.objects.filter(user=user).aggregate(
                    total=Sum('balance'),
                )['total']
                or 0,
            ),
            'total_expenses': float(
                Expense.objects.filter(user=user).aggregate(
                    total=Sum('amount'),
                )['total']
                or 0,
            ),
            'total_incomes': float(
                Income.objects.filter(user=user).aggregate(total=Sum('amount'))[
                    'total'
                ]
                or 0,
            ),
            'receipts_count': Receipt.objects.filter(user=user).count(),
        },
    }
