from typing import Any, Dict, Optional

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, UpdateView
from django.views.generic.list import ListView
from django_filters.views import FilterView
from hasta_la_vista_money import constants
from hasta_la_vista_money.custom_mixin import (
    DeleteObjectMixin,
    UpdateViewMixin,
)
from hasta_la_vista_money.expense.filters import ExpenseFilter
from hasta_la_vista_money.expense.forms import AddCategoryForm, AddExpenseForm
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.expense.services import (
    ExpenseService,
    ExpenseCategoryService,
    ReceiptExpenseService,
)
from hasta_la_vista_money.services.views import build_category_tree
from hasta_la_vista_money.users.models import User


class BaseView:
    """Base view class with common configuration."""

    template_name = 'expense/show_expense.html'
    success_url: Optional[str] = reverse_lazy('expense:list')


class ExpenseBaseView(BaseView):
    """Base view for expense-related operations."""

    model = Expense


class ExpenseCategoryBaseView(BaseView):
    """Base view for expense category operations."""

    model = ExpenseCategory


class ExpenseView(
    LoginRequiredMixin,
    ExpenseBaseView,
    SuccessMessageMixin,
    FilterView,
):
    """Main expense list view with filtering and pagination."""

    paginate_by = 10
    context_object_name = 'expense'
    filterset_class = ExpenseFilter
    no_permission_url = reverse_lazy('login')

    def get_context_data(self, *args, **kwargs) -> Dict[str, Any]:
        """
        Get context data for expense list view.

        Returns:
            Dict containing expense data, categories, and forms.
        """
        context = super().get_context_data(**kwargs)
        user = get_object_or_404(User, username=self.request.user)

        # Get services
        expense_service = ExpenseService(user)
        receipt_service = ReceiptExpenseService(user)

        # Get expense data
        expense_filter = ExpenseFilter(
            self.request.GET,
            queryset=Expense.objects.all(),
            user=self.request.user,
        )
        expenses = expense_filter.qs.select_related(
            'user',
            'category',
            'account',
        )

        # Get receipt expenses
        receipt_expenses = receipt_service.get_receipt_expenses()

        # Combine expenses and receipts
        all_expenses = list(expenses) + receipt_expenses

        # Calculate totals
        total_amount_page = sum(
            getattr(expense, 'amount', 0) for expense in all_expenses
        )
        total_amount_period = sum(
            getattr(expense, 'amount', 0) for expense in all_expenses
        )

        # Get categories
        expense_categories = expense_service.get_categories()
        flattened_categories = build_category_tree(
            expense_categories,
            depth=3,
        )

        # Get form
        add_expense_form = expense_service.get_expense_form()

        context.update(
            {
                'expense_filter': expense_filter,
                'categories': expense_categories,
                'expenses': all_expenses,
                'add_expense_form': add_expense_form,
                'flattened_categories': flattened_categories,
                'total_amount_page': total_amount_page,
                'total_amount_period': total_amount_period,
                'request': self.request,
            }
        )

        return context


class ExpenseCopyView(
    LoginRequiredMixin,
    SuccessMessageMixin,
    ExpenseBaseView,
    View,
):
    """View for copying an existing expense."""

    no_permission_url = reverse_lazy('login')

    def post(self, request, *args, **kwargs) -> HttpResponse:
        """Handle POST request to copy an expense."""
        expense_id = kwargs.get('pk')
        expense_service = ExpenseService(request.user)

        try:
            new_expense = expense_service.copy_expense(expense_id)
            messages.success(request, 'Расход успешно скопирован.')
            return redirect(
                reverse_lazy('expense:change', kwargs={'pk': new_expense.pk}),
            )
        except Exception as e:
            messages.error(request, f'Ошибка при копировании расхода: {str(e)}')
            return redirect('expense:list')


class ExpenseCreateView(
    LoginRequiredMixin,
    SuccessMessageMixin,
    ExpenseBaseView,
    CreateView,
):
    """View for creating a new expense."""

    no_permission_url = reverse_lazy('login')
    template_name = 'expense/add_expense.html'
    form_class = AddExpenseForm
    success_url: Optional[str] = reverse_lazy('expense:list')

    def get_form_kwargs(self) -> Dict[str, Any]:
        """Get form kwargs with user-specific querysets."""
        kwargs = super().get_form_kwargs()
        expense_service = ExpenseService(self.request.user)
        kwargs.update(expense_service.get_form_querysets())
        return kwargs

    def get_context_data(self, **kwargs) -> Dict[str, Any]:
        """Get context data for expense creation form."""
        context = super().get_context_data(**kwargs)
        if 'add_expense_form' not in context:
            context['add_expense_form'] = self.get_form()
        return context

    def form_valid(self, form) -> HttpResponse:
        """Handle valid form submission."""
        expense_service = ExpenseService(self.request.user)

        try:
            expense_service.create_expense(form)
            messages.success(self.request, constants.SUCCESS_EXPENSE_ADDED)
            return super().form_valid(form)
        except Exception as e:
            messages.error(self.request, f'Ошибка при создании расхода: {str(e)}')
            return self.form_invalid(form)

    def form_invalid(self, form) -> HttpResponse:
        """Handle invalid form submission."""
        return self.render_to_response(self.get_context_data(add_expense_form=form))


class ExpenseUpdateView(
    LoginRequiredMixin,
    SuccessMessageMixin,
    ExpenseBaseView,
    UpdateView,
    UpdateViewMixin,
):
    """View for updating an existing expense."""

    template_name = 'expense/change_expense.html'
    form_class = AddExpenseForm
    no_permission_url = reverse_lazy('login')

    def get_object(self, queryset=None) -> Expense:
        """Get the expense object to update."""
        return get_object_or_404(
            Expense,
            pk=self.kwargs['pk'],
            user=self.request.user,
        )

    def get_form_kwargs(self) -> Dict[str, Any]:
        """Get form kwargs with user-specific querysets."""
        kwargs = super().get_form_kwargs()
        expense_service = ExpenseService(self.request.user)
        kwargs.update(expense_service.get_form_querysets())
        return kwargs

    def get_context_data(self, **kwargs) -> Dict[str, Any]:
        """Get context data for expense update form."""
        context = super().get_context_data(**kwargs)
        context['add_expense_form'] = self.get_form()
        return context

    def form_valid(self, form) -> HttpResponse:
        """Handle valid form submission."""
        expense_service = ExpenseService(self.request.user)

        try:
            expense_service.update_expense(self.object, form)
            messages.success(self.request, constants.SUCCESS_EXPENSE_UPDATE)
            return super().form_valid(form)
        except Exception as e:
            messages.error(self.request, f'Ошибка при обновлении расхода: {str(e)}')
            return self.form_invalid(form)


class ExpenseDeleteView(LoginRequiredMixin, ExpenseBaseView, DetailView, DeleteView):
    """View for deleting an expense."""

    context_object_name = 'expense'
    no_permission_url = reverse_lazy('login')

    def form_valid(self, form) -> HttpResponse:
        """Handle valid form submission for deletion."""
        expense_service = ExpenseService(self.request.user)

        try:
            expense_service.delete_expense(self.get_object())
            messages.success(self.request, constants.SUCCESS_EXPENSE_DELETED)
            return super().form_valid(form)
        except Exception as e:
            messages.error(self.request, f'Ошибка при удалении расхода: {str(e)}')
            return redirect('expense:list')


class ExpenseCategoryView(LoginRequiredMixin, ListView):
    """View for displaying expense categories."""

    template_name = 'expense/show_category_expense.html'
    model = ExpenseCategory
    depth = 3

    def get_context_data(self, **kwargs) -> Dict[str, Any]:
        """Get context data for category list."""
        user = get_object_or_404(User, username=self.request.user)
        category_service = ExpenseCategoryService(user)

        expense_categories = category_service.get_categories()
        flattened_categories = build_category_tree(
            expense_categories,
            depth=self.depth,
        )

        context = super().get_context_data(**kwargs)
        context['flattened_categories'] = flattened_categories
        return context


class ExpenseCategoryCreateView(LoginRequiredMixin, CreateView):
    """View for creating a new expense category."""

    model = ExpenseCategory
    template_name = 'expense/add_category_expense.html'
    form_class = AddCategoryForm
    success_url: str = reverse_lazy('expense:category_list')

    def get_form_kwargs(self) -> Dict[str, Any]:
        """Get form kwargs with user-specific queryset."""
        kwargs = super().get_form_kwargs()
        category_service = ExpenseCategoryService(self.request.user)
        kwargs['category_queryset'] = category_service.get_categories_queryset()
        return kwargs

    def form_valid(self, form) -> HttpResponse:
        """Handle valid form submission."""
        category_service = ExpenseCategoryService(self.request.user)

        try:
            category_name = self.request.POST.get('name')
            category_service.create_category(form)
            messages.success(
                self.request,
                f'Категория "{category_name}" была успешно добавлена!',
            )
            return redirect(self.success_url)
        except Exception as e:
            messages.error(self.request, f'Ошибка при создании категории: {str(e)}')
            return self.form_invalid(form)

    def form_invalid(self, form) -> HttpResponse:
        """Handle invalid form submission."""
        messages.error(
            self.request,
            'Ошибка при добавлении категории. Проверьте введенные данные.',
        )
        return self.render_to_response(self.get_context_data(form=form))


class ExpenseCategoryDeleteView(ExpenseCategoryBaseView, DeleteObjectMixin):
    """View for deleting an expense category."""

    success_message = constants.SUCCESS_CATEGORY_EXPENSE_DELETED
    error_message = constants.ACCESS_DENIED_DELETE_EXPENSE_CATEGORY


class ExpenseGroupAjaxView(LoginRequiredMixin, View):
    """AJAX view for getting expenses by group."""

    def get(self, request, *args, **kwargs) -> HttpResponse:
        """Handle GET request for group expenses."""
        group_id = request.GET.get('group_id')
        expense_service = ExpenseService(request.user)

        try:
            all_expenses = expense_service.get_expenses_by_group(group_id)
            context = {'expenses': all_expenses, 'request': request}
            html = render_to_string(
                'expense/_expense_table_block.html',
                context,
                request=request,
            )
            return HttpResponse(html)
        except Exception as e:
            return HttpResponse(f'Ошибка: {str(e)}', status=500)


class ExpenseDataAjaxView(LoginRequiredMixin, View):
    """AJAX view for getting expense data as JSON."""

    def get(self, request, *args, **kwargs) -> JsonResponse:
        """Handle GET request for expense data."""
        group_id = request.GET.get('group_id')
        expense_service = ExpenseService(request.user)

        try:
            all_data = expense_service.get_expense_data(group_id)
            return JsonResponse({'data': all_data})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
