"""Data preparation utilities for finance account operations.

This module provides functions for collecting and organizing financial data
from the database, including income and expense information filtered by user.
"""

from operator import itemgetter
from typing import Any

from hasta_la_vista_money.users.models import User


def collect_info_income(user: User) -> Any:
    """Collect income information from database filtered by user.

    Retrieves income records for the specified user with related account
    and category information for display and analysis purposes.

    Args:
        user: The user whose income records to retrieve.

    Returns:
        Queryset containing income records with related data.
    """
    return user.income_users.select_related('user').values(
        'id',
        'date',
        'account__name_account',
        'category__name',
        'amount',
    )


def collect_info_expense(user: User) -> Any:
    """Collect expense information from database filtered by user.

    Retrieves expense records for the specified user with related account
    and category information for display and analysis purposes.

    Args:
        user: The user whose expense records to retrieve.

    Returns:
        Queryset containing expense records with related data.
    """
    return user.expense_users.select_related('user').values(
        'id',
        'date',
        'account__name_account',
        'category__name',
        'amount',
    )


def sort_expense_income(expenses: Any, income: Any) -> list[Any]:
    """Create a sorted list combining expenses and income.

    Merges expense and income data into a single list sorted by date
    in descending order for chronological display.

    Args:
        expenses: Queryset of expense records.
        income: Queryset of income records.

    Returns:
        List of combined financial records sorted by date (newest first).
    """
    return sorted(
        list(expenses) + list(income),
        key=itemgetter('date'),
        reverse=True,
    )
