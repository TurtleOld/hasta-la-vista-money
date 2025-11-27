from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any, NamedTuple, cast

from django.db.models import Sum
from django.db.models.functions import ExtractYear, TruncMonth
from django.db.models.query import QuerySet
from django.http import HttpRequest
from django.utils.formats import date_format

from core.protocols.services import AccountServiceProtocol
from hasta_la_vista_money.constants import (
    RECEIPT_CATEGORY_NAME,
    RECEIPT_OPERATION_PURCHASE,
)
from hasta_la_vista_money.expense.forms import AddCategoryForm, AddExpenseForm
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.services.views import (
    get_new_type_operation,
    get_queryset_type_income_expenses,
)
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.expense.repositories import (
        ExpenseCategoryRepository,
        ExpenseRepository,
    )
    from hasta_la_vista_money.finance_account.repositories.account_repository import (  # noqa: E501
        AccountRepository,
    )
    from hasta_la_vista_money.receipts.repositories.receipt_repository import (
        ReceiptRepository,
    )


class ExpenseService:
    """Service class for expense-related operations."""

    def __init__(
        self,
        user: User,
        request: HttpRequest,
        account_service: AccountServiceProtocol,
        account_repository: 'AccountRepository',
        expense_repository: 'ExpenseRepository',
        expense_category_repository: 'ExpenseCategoryRepository',
        receipt_repository: 'ReceiptRepository',
        receipt_expense_service_factory: Callable[..., 'ReceiptExpenseService'],
    ):
        self.user = user
        self.request = request
        self.account_service = account_service
        self.account_repository = account_repository
        self.expense_repository = expense_repository
        self.expense_category_repository = expense_category_repository
        self.receipt_repository = receipt_repository
        self.receipt_expense_service = receipt_expense_service_factory(
            user=user,
            request=request,
            expense_category_repository=expense_category_repository,
            receipt_repository=receipt_repository,
        )

    def get_categories(self) -> Iterable[dict[str, str | int | None]]:
        """Get expense categories for the user."""
        qs = (
            self.user.category_expense_users.select_related('user')  # type: ignore[attr-defined]
            .values(
                'id',
                'name',
                'parent_category',
                'parent_category__name',
            )
            .order_by('name', 'parent_category')
        )
        return cast('Iterable[dict[str, str | int | None]]', qs)

    def get_categories_queryset(self) -> QuerySet[ExpenseCategory]:
        """Get categories queryset for forms."""
        return (
            self.user.category_expense_users.select_related('user')  # type: ignore[attr-defined]
            .order_by('parent_category__name', 'name')
            .all()
        )

    def get_form_querysets(self) -> dict[str, Any]:
        """Get form querysets for expense forms."""
        return {
            'category_queryset': self.get_categories_queryset(),
            'account_queryset': self.account_repository.get_by_user(self.user),
        }

    def get_expense_form(self) -> AddExpenseForm:
        """Get expense form with user-specific querysets."""
        return AddExpenseForm(
            category_queryset=self.get_categories_queryset(),
            account_queryset=self.account_repository.get_by_user(self.user),
        )

    def create_expense(
        self,
        form: AddExpenseForm,
    ) -> Expense:
        """Create a new expense."""
        expense_data = form.cleaned_data
        expense = self.expense_repository.create_expense(
            user=self.user,
            account=expense_data['account'],
            category=expense_data['category'],
            amount=expense_data['amount'],
            date=expense_data['date'],
        )

        if expense.amount is not None:
            self.account_service.apply_receipt_spend(
                expense.account,
                expense.amount,
            )

        return expense

    def update_expense(
        self,
        expense: Expense,
        form: AddExpenseForm,
    ) -> None:
        """Update an existing expense."""
        expense_updated: Expense = get_queryset_type_income_expenses(
            expense.pk,
            Expense,
            form,
        )

        amount = form.cleaned_data['amount']
        account = form.cleaned_data['account']
        account_balance = self.account_repository.get_by_id(account.pk)
        old_account_balance = self.account_repository.get_by_id(
            expense_updated.account.pk,
        )

        if account_balance.user != self.user:
            error_msg = 'У вас нет прав для выполнения этого действия'
            raise ValueError(error_msg)

        self.account_service.reconcile_account_balances(
            old_account=old_account_balance,
            new_account=account_balance,
            old_total_sum=expense_updated.amount,
            new_total_sum=amount,
        )

        expense_updated.user = self.user
        expense_updated.amount = amount
        expense_updated.account = account
        expense_updated.save()

    def delete_expense(
        self,
        expense: Expense,
    ) -> None:
        """Delete an expense and restore account balance."""
        account = expense.account
        amount = expense.amount
        account_balance = self.account_repository.get_by_id(account.pk)

        if account_balance.user != self.user:
            error_msg = 'У вас нет прав для выполнения этого действия'
            raise ValueError(error_msg)

        self.account_service.refund_to_account(account_balance, amount)
        account_balance.save()
        expense.delete()

    def copy_expense(
        self,
        expense_id: int,
    ) -> Expense:
        """Copy an existing expense."""
        new_expense = get_new_type_operation(Expense, expense_id, self.request)
        valid_expense = self.expense_repository.get_by_id(new_expense.pk)

        if valid_expense.account is not None:
            self.account_service.apply_receipt_spend(
                valid_expense.account,
                valid_expense.amount,
            )

        return valid_expense

    def get_expenses_by_group(self, group_id: str | None) -> list[Any]:
        """Get expenses filtered by group."""
        expenses = self.expense_repository.filter(id__isnull=True)
        receipt_expense_list = []
        user = User.objects.prefetch_related('groups').get(pk=self.user.pk)

        group_users = self.account_service.get_users_for_group(user, group_id)

        if group_users:
            if len(group_users) == 1 and group_users[0] == user:
                expenses = self.expense_repository.get_by_user(self.user)
            else:
                expenses = self.expense_repository.get_by_user_and_group(
                    self.user,
                    group_id,
                )

        expenses = expenses.order_by('-date')

        if group_users:
            receipt_expense_list = (
                self.receipt_expense_service.get_receipt_expenses_by_users(
                    group_users,
                )
            )

        return list(expenses) + receipt_expense_list

    def get_expense_data(self, group_id: str | None) -> list[dict[str, Any]]:
        """Get expense data as dictionary for AJAX responses."""
        expenses = self.expense_repository.filter(id__isnull=True)
        receipt_expense_list = []
        user = User.objects.prefetch_related('groups').get(pk=self.user.pk)

        group_users = self.account_service.get_users_for_group(user, group_id)

        if group_users:
            if len(group_users) == 1 and group_users[0] == user:
                expenses = self.expense_repository.get_by_user(self.user)
            else:
                expenses = self.expense_repository.get_by_user_and_group(
                    self.user,
                    group_id,
                )

        if group_users:
            receipt_expense_list = (
                self.receipt_expense_service.get_receipt_data_by_users(
                    group_users,
                )
            )

        data = [
            {
                'id': expense.pk,
                'date': expense.date.strftime('%d.%m.%Y'),
                'amount': float(expense.amount) if expense.amount else 0,
                'category_name': expense.category.name,
                'account_name': expense.account.name_account,
                'user_name': expense.user.get_full_name()
                or expense.user.username,
                'user_id': expense.user.pk,
                'is_receipt': False,
                'receipt_id': None,
                'actions': '',  # Will be generated on frontend
            }
            for expense in expenses
        ]

        return data + receipt_expense_list


class ExpenseCategoryService:
    """Service class for expense category operations."""

    def __init__(
        self,
        user: User,
        request: HttpRequest,
        expense_category_repository: 'ExpenseCategoryRepository',
    ):
        self.user = user
        self.request = request
        self.expense_category_repository = expense_category_repository

    def get_categories(self) -> Iterable[dict[str, str | int | None]]:
        """Get expense categories for the user."""
        qs = (
            self.user.category_expense_users.select_related('parent_category')  # type: ignore[attr-defined]
            .values(
                'id',
                'name',
                'parent_category',
                'parent_category__name',
            )
            .order_by('name', 'parent_category')
        )
        return cast('Iterable[dict[str, str | int | None]]', qs)

    def get_categories_queryset(self) -> QuerySet[ExpenseCategory]:
        """Get categories queryset for forms."""
        return (
            self.user.category_expense_users.select_related('user')  # type: ignore[attr-defined]
            .order_by('parent_category__name', 'name')
            .all()
        )

    def create_category(self, form: AddCategoryForm) -> ExpenseCategory:
        """Create a new expense category."""
        category = form.save(commit=False)
        category.user = self.user
        return self.expense_category_repository.create_category(
            user=category.user,
            name=category.name,
            parent_category=category.parent_category,
        )


class ReceiptExpenseService:
    """Service class for receipt expense operations."""

    def __init__(
        self,
        user: User,
        request: HttpRequest,
        expense_category_repository: 'ExpenseCategoryRepository',
        receipt_repository: 'ReceiptRepository',
    ):
        self.user = user
        self.request = request
        self.expense_category_repository = expense_category_repository
        self.receipt_repository = receipt_repository

    def get_receipt_expenses(self) -> list[Any]:
        """Get receipt expenses for the user."""
        receipt_category = self.expense_category_repository.filter(
            user=self.user,
            name=RECEIPT_CATEGORY_NAME,
        ).first()

        if not receipt_category:
            return []

        class ReceiptExpense(NamedTuple):
            id: str
            date: Any
            amount: Any
            category: Any
            account: Any
            user: Any
            is_receipt: bool
            date_label: str

        receipt_expenses = (
            self.receipt_repository.filter(
                user=self.user,
                operation_type=RECEIPT_OPERATION_PURCHASE,
            )
            .annotate(
                month=TruncMonth('receipt_date'),
                year=ExtractYear('receipt_date'),
            )
            .values(
                'month',
                'year',
                'account__id',
                'account__name_account',
                'total_sum',
            )
            .order_by('-year', '-month')
        )

        return [
            ReceiptExpense(
                id=f'receipt_{receipt["month"].year}{receipt["month"].strftime("%m")}_{receipt["account__name_account"]}',
                date=receipt['month'],
                amount=receipt['total_sum'],
                category=receipt_category,
                account=type(
                    'AccountObj',
                    (),
                    {'name_account': receipt['account__name_account']},
                )(),
                user=self.user,
                is_receipt=True,
                date_label=date_format(receipt['month'], 'F Y'),
            )
            for receipt in receipt_expenses
        ]

    def get_receipt_expenses_by_users(
        self,
        users: list[User],
    ) -> list[dict[str, Any]]:
        """Get receipt expenses for multiple users."""
        receipt_expenses = (
            self.receipt_repository.filter(
                user__in=users,
                operation_type=RECEIPT_OPERATION_PURCHASE,
            )
            .select_related('user', 'account')
            .annotate(
                month=TruncMonth('receipt_date'),
                year=ExtractYear('receipt_date'),
            )
            .values(
                'month',
                'year',
                'account__id',
                'account__name_account',
                'user',
                'user__username',
            )
            .annotate(amount=Sum('total_sum'))
            .order_by('-year', '-month')
        )

        return [
            {
                'id': (
                    f'receipt_{receipt["year"]}'
                    f'{receipt["month"].strftime("%m")}_'
                    f'{receipt["account__name_account"]}_'
                    f'{receipt["user"]}'
                ),
                'date': receipt['month'],
                'date_label': (
                    receipt['month'].strftime('%B %Y')
                    if receipt['month']
                    else ''
                ),
                'amount': receipt['amount'],
                'category': {
                    'name': RECEIPT_CATEGORY_NAME,
                    'parent_category': None,
                },
                'account': {
                    'name_account': receipt['account__name_account'],
                },
                'user': {'username': receipt['user__username']},
                'is_receipt': True,
            }
            for receipt in receipt_expenses
        ]

    def get_receipt_data_by_users(
        self,
        users: list[User],
    ) -> list[dict[str, Any]]:
        """Get receipt data as dictionary for AJAX responses."""
        receipts = self.receipt_repository.filter(
            user__in=users,
            operation_type=RECEIPT_OPERATION_PURCHASE,
        ).select_related('account', 'user')

        return [
            {
                'id': f'receipt_{receipt.pk}',
                'date': receipt.receipt_date.strftime('%d.%m.%Y'),
                'amount': float(receipt.total_sum) if receipt.total_sum else 0,
                'category_name': RECEIPT_CATEGORY_NAME,
                'account_name': receipt.account.name_account,
                'user_name': receipt.user.get_full_name()
                or receipt.user.username,
                'user_id': receipt.user.pk,
                'is_receipt': True,
                'receipt_id': receipt.pk,
                'actions': '',  # No buttons for receipts
            }
            for receipt in receipts
        ]
