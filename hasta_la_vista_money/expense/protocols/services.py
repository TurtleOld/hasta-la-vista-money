from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from django.db.models import QuerySet

from hasta_la_vista_money.expense.models import Expense, ExpenseCategory

if TYPE_CHECKING:
    from hasta_la_vista_money.expense.forms import AddExpenseForm


@runtime_checkable
class ExpenseServiceProtocol(Protocol):
    def get_categories(self) -> Iterable[dict[str, str | int | None]]: ...
    def get_categories_queryset(self) -> QuerySet['ExpenseCategory']: ...
    def get_form_querysets(self) -> dict[str, Any]: ...
    def get_expense_form(self) -> 'AddExpenseForm': ...
    def create_expense(
        self,
        form: 'AddExpenseForm',
    ) -> Expense: ...
    def update_expense(
        self,
        expense: 'Expense',
        form: 'AddExpenseForm',
    ) -> None: ...
    def delete_expense(
        self,
        expense: 'Expense',
    ) -> None: ...
    def copy_expense(
        self,
        expense_id: int,
    ) -> 'Expense': ...
    def get_expenses_by_group(
        self,
        group_id: str | None,
    ) -> list[Any]: ...
    def get_expense_data(
        self,
        group_id: str | None,
    ) -> list[dict[str, Any]]: ...
