"""Protocol interfaces for budget services."""

from collections.abc import Iterable
from datetime import date
from typing import Protocol, runtime_checkable

from hasta_la_vista_money.budget.services.budget import (
    AggregateBudgetDataDict,
    AggregateExpenseApiDict,
    AggregateExpenseTableDict,
    AggregateIncomeApiDict,
    AggregateIncomeTableDict,
    BudgetLimitOverviewDict,
)
from hasta_la_vista_money.transactions.models import Category
from hasta_la_vista_money.users.models import User


@runtime_checkable
class BudgetServiceProtocol(Protocol):
    """Protocol for budget aggregation service."""

    def aggregate_budget_limit_overview(
        self,
        user: User,
        months: list[date],
        expense_categories: list[Category],
        users: Iterable[User] | None = None,
    ) -> BudgetLimitOverviewDict: ...

    def aggregate_budget_data(
        self,
        user: User,
        months: list[date],
        expense_categories: list[Category],
        income_categories: list[Category],
        users: Iterable[User] | None = None,
    ) -> AggregateBudgetDataDict: ...

    def aggregate_expense_table(
        self,
        user: User,
        months: list[date],
        expense_categories: list[Category],
        users: Iterable[User] | None = None,
    ) -> AggregateExpenseTableDict: ...

    def aggregate_income_table(
        self,
        user: User,
        months: list[date],
        income_categories: list[Category],
        users: Iterable[User] | None = None,
    ) -> AggregateIncomeTableDict: ...

    def aggregate_expense_api(
        self,
        user: User,
        months: list[date],
        expense_categories: list[Category],
        users: Iterable[User] | None = None,
    ) -> AggregateExpenseApiDict: ...

    def aggregate_income_api(
        self,
        user: User,
        months: list[date],
        income_categories: list[Category],
        users: Iterable[User] | None = None,
    ) -> AggregateIncomeApiDict: ...
