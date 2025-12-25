"""Data preparation utilities for finance account operations.

This module provides functions for collecting and organizing financial data
from the database, including income and expense information filtered by user.
"""

from datetime import date, datetime
from decimal import Decimal
from operator import itemgetter
from typing import cast

from typing_extensions import TypedDict

from hasta_la_vista_money.users.models import User


class IncomeInfoDict(TypedDict):
    """Income information dictionary.

    Attributes:
        id: Income transaction ID.
        date: Transaction date.
        account__name_account: Account name.
        category__name: Category name.
        amount: Income amount.
    """

    id: int
    date: datetime | date
    account__name_account: str
    category__name: str
    amount: Decimal


class ExpenseInfoDict(TypedDict):
    """Expense information dictionary.

    Attributes:
        id: Expense transaction ID.
        date: Transaction date.
        account__name_account: Account name.
        category__name: Category name.
        amount: Expense amount.
    """

    id: int
    date: datetime | date
    account__name_account: str
    category__name: str
    amount: Decimal


def collect_info_income(user: User) -> list[IncomeInfoDict]:
    """Collect income information from database filtered by user.

    Retrieves income records for the specified user with related account
    and category information for display and analysis purposes.

    Args:
        user: The user whose income records to retrieve.

    Returns:
        List of dictionaries containing income records with related data.
    """
    queryset = user.income_users.select_related('user').values(
        'id',
        'date',
        'account__name_account',
        'category__name',
        'amount',
    )
    return cast('list[IncomeInfoDict]', list(queryset))


def collect_info_expense(user: User) -> list[ExpenseInfoDict]:
    """Collect expense information from database filtered by user.

    Retrieves expense records for the specified user with related account
    and category information for display and analysis purposes.

    Args:
        user: The user whose expense records to retrieve.

    Returns:
        List of dictionaries containing expense records with related data.
    """
    queryset = user.expense_users.select_related('user').values(
        'id',
        'date',
        'account__name_account',
        'category__name',
        'amount',
    )
    return cast('list[ExpenseInfoDict]', list(queryset))


def sort_expense_income(
    expenses: list[ExpenseInfoDict] | None,
    income: list[IncomeInfoDict] | None,
) -> list[ExpenseInfoDict | IncomeInfoDict]:
    """Create a sorted list combining expenses and income.

    Merges expense and income data into a single list sorted by date
    in descending order for chronological display.

    Args:
        expenses: Queryset of expense records.
        income: Queryset of income records.

    Returns:
        List of combined financial records sorted by date (newest first).
    """
    expenses_list = list(expenses or [])
    income_list = list(income or [])

    return sorted(
        expenses_list + income_list,
        key=itemgetter('date'),
        reverse=True,
    )
