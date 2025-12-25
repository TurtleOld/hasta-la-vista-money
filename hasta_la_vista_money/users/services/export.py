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
    """User information for export.

    Attributes:
        username: Username.
        email: Email address.
        first_name: First name.
        last_name: Last name.
        date_joined: Date joined (ISO format).
        last_login: Last login date (ISO format) or None.
    """

    username: str
    email: str
    first_name: str
    last_name: str
    date_joined: str
    last_login: str | None


class StatisticsDict(TypedDict):
    """Statistics for export.

    Attributes:
        total_balance: Total account balance.
        total_expenses: Total expenses.
        total_incomes: Total income.
        receipts_count: Number of receipts.
    """

    total_balance: float
    total_expenses: float
    total_incomes: float
    receipts_count: int


class AccountDict(TypedDict):
    """Account data dictionary.

    Attributes:
        name_account: Account name.
        balance: Account balance.
        currency: Currency code.
        created_at: Account creation date or None.
    """

    name_account: str
    balance: Decimal
    currency: str
    created_at: datetime | None


class ExpenseDict(TypedDict):
    """Expense data dictionary.

    Attributes:
        amount: Expense amount.
        date: Expense date.
        category__name: Category name.
        account__name_account: Account name.
    """

    amount: Decimal
    date: datetime
    category__name: str
    account__name_account: str


class IncomeDict(TypedDict):
    """Income data dictionary.

    Attributes:
        amount: Income amount.
        date: Income date.
        category__name: Category name.
        account__name_account: Account name.
    """

    amount: Decimal
    date: datetime
    category__name: str
    account__name_account: str


class ReceiptDict(TypedDict):
    """Receipt data dictionary.

    Attributes:
        receipt_date: Receipt date.
        seller__name_seller: Seller name.
        total_sum: Total receipt sum.
    """

    receipt_date: datetime
    seller__name_seller: str
    total_sum: Decimal


class UserExportData(TypedDict):
    """User export data.

    Attributes:
        user_info: User information.
        accounts: List of accounts.
        expenses: List of expenses.
        incomes: List of income.
        receipts: List of receipts.
        statistics: Statistics summary.
    """

    user_info: UserInfoDict
    accounts: list[AccountDict]
    expenses: list[ExpenseDict]
    incomes: list[IncomeDict]
    receipts: list[ReceiptDict]
    statistics: StatisticsDict


def get_user_export_data(user: User) -> UserExportData:
    """Get user data for export.

    Args:
        user: User to export data for.

    Returns:
        UserExportData dictionary with all user data.
    """
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
