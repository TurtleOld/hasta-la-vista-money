from typing import Any, NamedTuple

from django.contrib.auth.models import Group
from django.db.models import Sum
from django.db.models.functions import ExtractYear, TruncMonth
from django.db.models.query import QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.utils.formats import date_format

from hasta_la_vista_money.constants import (
    RECEIPT_CATEGORY_NAME,
    RECEIPT_OPERATION_PURCHASE,
)
from hasta_la_vista_money.expense.forms import AddCategoryForm, AddExpenseForm
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.services import AccountService
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.services.views import (
    get_new_type_operation,
    get_queryset_type_income_expenses,
)
from hasta_la_vista_money.users.models import User


class ExpenseService:
    """Service class for expense-related operations."""

    def __init__(self, user: User, request: HttpRequest):
        self.user = user
        self.request = request

    def get_categories(self) -> QuerySet[dict[str, Any]]:
        """Get expense categories for the user."""
        return (
            self.user.category_expense_users.select_related('user')
            .values(
                'id',
                'name',
                'parent_category',
                'parent_category__name',
            )
            .order_by('name', 'parent_category')
        )

    def get_categories_queryset(self) -> QuerySet[ExpenseCategory]:
        """Get categories queryset for forms."""
        return (
            self.user.category_expense_users.select_related('user')
            .order_by('parent_category__name', 'name')
            .all()
        )

    def get_form_querysets(self) -> dict[str, Any]:
        """Get form querysets for expense forms."""
        return {
            'category_queryset': self.get_categories_queryset(),
            'account_queryset': Account.objects.filter(user=self.user),
        }

    def get_expense_form(self) -> AddExpenseForm:
        """Get expense form with user-specific querysets."""
        return AddExpenseForm(  # type: ignore[call-untyped]
            category_queryset=self.get_categories_queryset(),
            account_queryset=Account.objects.filter(user=self.user),
        )

    def create_expense(self, form) -> Expense:
        """Create a new expense."""
        expense = form.save(commit=False)
        expense.user = self.user
        expense.save()

        if expense.account and expense.amount is not None:
            AccountService.apply_receipt_spend(expense.account, expense.amount)

        return expense

    def update_expense(self, expense: Expense, form) -> None:
        """Update an existing expense."""
        expense = get_queryset_type_income_expenses(
            expense.id,
            Expense,
            form,
        )

        amount = form.cleaned_data.get('amount')
        account = form.cleaned_data.get('account')
        account_balance = get_object_or_404(Account, id=account.id)
        old_account_balance = get_object_or_404(Account, id=expense.account.id)

        if account_balance.user != self.user:
            error_msg = 'У вас нет прав для выполнения этого действия'
            raise ValueError(error_msg)

        # Корректировка балансов через сервис аккаунтов
        AccountService.adjust_on_receipt_update(
            old_account=old_account_balance,
            new_account=account_balance,
            old_total_sum=expense.amount,
            new_total_sum=amount,
        )

        # Update expense
        expense.user = self.user
        expense.amount = amount
        expense.save()

    def delete_expense(self, expense: Expense) -> None:
        """Delete an expense and restore account balance."""
        account = expense.account
        amount = expense.amount
        account_balance = get_object_or_404(Account, id=account.id)

        if account_balance.user != self.user:
            error_msg = 'У вас нет прав для выполнения этого действия'
            raise ValueError(error_msg)

        # Возврат средств при удалении расхода
        account_balance.balance += amount
        account_balance.save()
        expense.delete()

    def copy_expense(self, expense_id: int) -> Expense:
        """Copy an existing expense."""
        new_expense = get_new_type_operation(Expense, expense_id, self.request)
        valid_expense = get_object_or_404(Expense, pk=new_expense.pk)

        if valid_expense.account:
            valid_expense.account.balance -= valid_expense.amount
            valid_expense.account.save()

        return valid_expense

    def get_expenses_by_group(self, group_id: str | None) -> list[Any]:
        """Get expenses filtered by group."""
        expenses = Expense.objects.none()
        receipt_expense_list = []

        if not group_id or group_id == 'my':
            expenses = Expense.objects.filter(user=self.user).select_related(
                'user',
                'category',
                'account',
            )
            group_users = [self.user]
        elif self.user.groups.filter(id=group_id).exists():
            group_users = list(User.objects.filter(groups__id=group_id))
            expenses = Expense.objects.filter(
                user__in=group_users,
            ).select_related('user', 'category', 'account')
        else:
            group_users = []

        expenses = expenses.order_by('-date')

        if group_users:
            receipt_service = ReceiptExpenseService(self.user, self.request)
            receipt_expense_list = (
                receipt_service.get_receipt_expenses_by_users(
                    group_users,
                )
            )

        return list(expenses) + receipt_expense_list

    def get_expense_data(self, group_id: str | None) -> list[dict[str, Any]]:
        """Get expense data as dictionary for AJAX responses."""
        expenses = Expense.objects.none()
        receipt_expense_list = []

        if group_id == 'my' or not group_id:
            expenses = Expense.objects.filter(user=self.user).select_related(
                'user',
                'category',
                'account',
            )
            group_users = [self.user]
        else:
            try:
                group = Group.objects.get(pk=group_id)
                group_users = list(group.user_set.all())
                expenses = Expense.objects.filter(
                    user__in=group_users,
                ).select_related('user', 'category', 'account')
            except Group.DoesNotExist:
                group_users = []
                expenses = Expense.objects.none()

        if group_users:
            receipt_service = ReceiptExpenseService(self.user, self.request)
            receipt_expense_list = receipt_service.get_receipt_data_by_users(
                group_users,
            )

        data = [
            {
                'id': expense.pk,
                'date': expense.date.strftime('%d.%m.%Y'),
                'amount': float(expense.amount)
                if expense.amount is not None
                else 0,
                'category_name': expense.category.name
                if expense.category
                else '',
                'account_name': expense.account.name_account
                if expense.account
                else '',
                'user_name': expense.user.get_full_name()
                or expense.user.username
                if expense.user
                else '',
                'user_id': expense.user.pk if expense.user else None,
                'is_receipt': False,
                'receipt_id': None,
                'actions': '',  # Will be generated on frontend
            }
            for expense in expenses
        ]

        return data + receipt_expense_list


class ExpenseCategoryService:
    """Service class for expense category operations."""

    def __init__(self, user: User, request: HttpRequest):
        self.user = user
        self.request = request

    def get_categories(self) -> QuerySet[dict[str, Any]]:
        """Get expense categories for the user."""
        return (
            self.user.category_expense_users.select_related('parent_category')
            .values(
                'id',
                'name',
                'parent_category',
                'parent_category__name',
            )
            .order_by('name', 'parent_category')
        )

    def get_categories_queryset(self) -> QuerySet[ExpenseCategory]:
        """Get categories queryset for forms."""
        return (
            self.user.category_expense_users.select_related('user')
            .order_by('parent_category__name', 'name')
            .all()
        )

    def create_category(self, form: AddCategoryForm) -> ExpenseCategory:
        """Create a new expense category."""
        category = form.save(commit=False)
        category.user = self.user
        category.save()
        return category


class ReceiptExpenseService:
    """Service class for receipt expense operations."""

    def __init__(self, user: User, request: HttpRequest):
        self.user = user
        self.request = request

    def get_receipt_expenses(self) -> list[Any]:
        """Get receipt expenses for the user."""
        receipt_category = ExpenseCategory.objects.filter(
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
            Receipt.objects.filter(
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
            Receipt.objects.filter(
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
        receipts = Receipt.objects.filter(
            user__in=users,
            operation_type=RECEIPT_OPERATION_PURCHASE,
        ).select_related('account', 'user')

        return [
            {
                'id': f'receipt_{receipt.pk}',
                'date': receipt.receipt_date.strftime('%d.%m.%Y')
                if receipt.receipt_date
                else '',
                'amount': float(receipt.total_sum)
                if receipt.total_sum is not None
                else 0,
                'category_name': RECEIPT_CATEGORY_NAME,
                'account_name': receipt.account.name_account
                if receipt.account
                else '',
                'user_name': receipt.user.get_full_name()
                or receipt.user.username
                if receipt.user
                else '',
                'user_id': receipt.user.pk if receipt.user else None,
                'is_receipt': True,
                'receipt_id': receipt.pk,
                'actions': '',  # No buttons for receipts
            }
            for receipt in receipts
        ]
