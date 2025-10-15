from abc import ABC, abstractmethod
from typing import Any, Dict

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseForbidden,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, UpdateView
from django.views.generic.list import ListView
from django_filters.views import FilterView
from hasta_la_vista_money import constants
from hasta_la_vista_money.custom_mixin import DeleteObjectMixin
from hasta_la_vista_money.expense.filters import ExpenseFilter
from hasta_la_vista_money.expense.forms import AddCategoryForm, AddExpenseForm
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.expense.services import (
    ExpenseCategoryService,
    ExpenseService,
    ReceiptExpenseService,
)
from hasta_la_vista_money.services.views import build_category_tree
from hasta_la_vista_money.users.models import User


class AbstractExpenseView(ABC):
    @property
    @abstractmethod
    def template_name(self) -> str: ...

    @property
    @abstractmethod
    def success_url(self) -> str: ...


class BaseView(AbstractExpenseView):
    """Base view class with common configuration."""

    pass


class ExpenseBaseView(BaseView):
    """Base view for expense-related operations."""

    model = Expense

    @property
    def template_name(self) -> str:
        return constants.EXPENSE_TEMPLATE

    @property
    def success_url(self) -> str:
        return str(reverse_lazy(constants.EXPENSE_LIST_URL))


class ExpenseCategoryBaseView(BaseView):
    """Base view for expense category operations."""

    model = ExpenseCategory

    @property
    def template_name(self) -> str:
        return constants.EXPENSE_CATEGORY_TEMPLATE

    @property
    def success_url(self) -> str:
        return str(reverse_lazy(constants.EXPENSE_CATEGORY_LIST_URL))


class ExpenseView(
    LoginRequiredMixin,
    SuccessMessageMixin[AddExpenseForm],
    FilterView[Expense, ExpenseFilter],  # type: ignore[misc]
):
    """Main expense list view with filtering and pagination."""

    model = Expense
    template_name = constants.EXPENSE_TEMPLATE
    paginate_by = 10
    context_object_name = 'expense'
    filterset_class = ExpenseFilter
    no_permission_url = reverse_lazy('login')

    def get_context_data(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """
        Get context data for expense list view.

        Returns:
            Dict containing expense data, categories, and forms.
        """
        context: Dict[str, Any] = super().get_context_data(**kwargs)
        user = get_object_or_404(User, username=self.request.user)

        expense_service = ExpenseService(user, self.request)
        receipt_service = ReceiptExpenseService(user, self.request)

        expense_queryset = Expense.objects.select_related(
            'user',
            'category',
            'account',
        )
        expense_filter: ExpenseFilter = ExpenseFilter(
            self.request.GET,
            queryset=expense_queryset,
            user=self.request.user,
        )
        expenses = expense_filter.qs

        receipt_expenses = receipt_service.get_receipt_expenses()

        all_expenses = list(expenses) + receipt_expenses

        total_amount_page = sum(
            getattr(expense, 'amount', 0) for expense in all_expenses
        )
        total_amount_period = sum(
            getattr(expense, 'amount', 0) for expense in all_expenses
        )

        expense_categories = expense_service.get_categories()
        flattened_categories = build_category_tree(
            expense_categories,
            depth=3,
        )

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
            },
        )

        return context


class ExpenseCopyView(
    LoginRequiredMixin,
    SuccessMessageMixin[AddExpenseForm],
    ExpenseBaseView,
    View,
):
    """View for copying an existing expense."""

    no_permission_url = reverse_lazy('login')

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Handle POST request to copy an expense."""
        if not isinstance(request.user, User):
            return HttpResponseForbidden(constants.USER_MUST_BE_AUTHENTICATED)
        expense_id = kwargs.get('pk')
        expense_service = ExpenseService(request.user, request)

        if expense_id is None:
            messages.error(request, _('Некорректный идентификатор расхода.'))
            return redirect(constants.EXPENSE_LIST_URL)

        try:
            new_expense = expense_service.copy_expense(int(expense_id))
            messages.success(request, _('Расход успешно скопирован.'))
            return redirect(
                reverse_lazy('expense:change', kwargs={'pk': new_expense.pk}),
            )
        except Exception as e:
            messages.error(
                request,
                _('Ошибка при копировании расхода: {error}').format(error=str(e)),
            )
            return redirect(constants.EXPENSE_LIST_URL)


class ExpenseCreateView(
    LoginRequiredMixin,
    SuccessMessageMixin[AddExpenseForm],
    CreateView[Expense, Any],
):
    """View for creating a new expense."""

    model = Expense
    template_name = 'expense/add_expense.html'
    form_class = AddExpenseForm
    success_url = reverse_lazy(constants.EXPENSE_LIST_URL)
    no_permission_url = reverse_lazy('login')

    def get_form_kwargs(self) -> Dict[str, Any]:
        """Get form kwargs with user-specific querysets."""
        kwargs = super().get_form_kwargs()
        if not isinstance(self.request.user, User):
            raise ValueError('User must be authenticated')
        expense_service = ExpenseService(self.request.user, self.request)
        kwargs.update(expense_service.get_form_querysets())
        return kwargs

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        """Get context data for expense creation form."""
        context = super().get_context_data(**kwargs)
        if 'add_expense_form' not in context:
            context['add_expense_form'] = self.get_form()
        return context

    def form_valid(self, form: Any) -> HttpResponse:
        """Handle valid form submission."""
        if not isinstance(self.request.user, User):
            raise ValueError('User must be authenticated')
        expense_service = ExpenseService(self.request.user, self.request)

        try:
            expense_service.create_expense(form)
            messages.success(self.request, constants.SUCCESS_EXPENSE_ADDED)
            return super().form_valid(form)
        except Exception as e:
            messages.error(
                self.request,
                _('Ошибка при создании расхода: {error}').format(error=str(e)),
            )
            return self.form_invalid(form)

    def form_invalid(self, form: Any) -> HttpResponse:
        """Handle invalid form submission."""
        return self.render_to_response(self.get_context_data(add_expense_form=form))


class ExpenseUpdateView(
    LoginRequiredMixin,
    SuccessMessageMixin[AddExpenseForm],
    UpdateView[Expense, AddExpenseForm],
):
    """View for updating an existing expense."""

    model = Expense
    template_name = 'expense/change_expense.html'
    form_class = AddExpenseForm
    success_url = reverse_lazy(constants.EXPENSE_LIST_URL)
    no_permission_url = reverse_lazy('login')

    def get_object(self, queryset: Any = None) -> Expense:
        """Get the expense object to update."""
        return get_object_or_404(
            Expense.objects.select_related('user', 'category', 'account'),
            pk=self.kwargs['pk'],
            user=self.request.user,
        )

    def get_form_kwargs(self) -> Dict[str, Any]:
        """Get form kwargs with user-specific querysets."""
        kwargs = super().get_form_kwargs()
        if not isinstance(self.request.user, User):
            raise ValueError(constants.USER_MUST_BE_AUTHENTICATED)
        expense_service = ExpenseService(self.request.user, self.request)
        kwargs.update(expense_service.get_form_querysets())
        return kwargs

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        """Get context data for expense update form."""
        context = super().get_context_data(**kwargs)
        context['add_expense_form'] = self.get_form()
        return context

    def form_valid(self, form: Any) -> HttpResponse:
        """Handle valid form submission."""
        if not isinstance(self.request.user, User):
            raise ValueError(constants.USER_MUST_BE_AUTHENTICATED)
        expense_service = ExpenseService(self.request.user, self.request)

        try:
            expense_service.update_expense(self.object, form)
            messages.success(self.request, constants.SUCCESS_EXPENSE_UPDATE)
            return super().form_valid(form)
        except Exception as e:
            messages.error(
                self.request,
                _('Ошибка при обновлении расхода: {error}').format(error=str(e)),
            )
            return self.form_invalid(form)


class ExpenseDeleteView(
    LoginRequiredMixin,
    DetailView[Expense],
    DeleteView[Expense, Any],
):
    """View for deleting an expense."""

    model = Expense
    template_name = constants.EXPENSE_TEMPLATE
    success_url = reverse_lazy(constants.EXPENSE_LIST_URL)
    context_object_name = 'expense'
    no_permission_url = reverse_lazy('login')

    def form_valid(self, form: Any) -> HttpResponse:
        """Handle valid form submission for deletion."""
        if not isinstance(self.request.user, User):
            raise ValueError(constants.USER_MUST_BE_AUTHENTICATED)
        expense_service = ExpenseService(self.request.user, self.request)

        try:
            expense_service.delete_expense(self.get_object())
            messages.success(self.request, constants.SUCCESS_EXPENSE_DELETED)
            return super().form_valid(form)
        except Exception as e:
            messages.error(
                self.request,
                _('Ошибка при удалении расхода: {error}').format(error=str(e)),
            )
            return redirect(constants.EXPENSE_LIST_URL)


class ExpenseCategoryView(LoginRequiredMixin, ListView[ExpenseCategory]):
    """View for displaying expense categories."""

    template_name = constants.EXPENSE_CATEGORY_TEMPLATE
    model = ExpenseCategory
    depth = 3

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        """Get context data for category list."""
        user = get_object_or_404(User, username=self.request.user)
        category_service = ExpenseCategoryService(user, self.request)

        expense_categories = category_service.get_categories()
        flattened_categories = build_category_tree(
            expense_categories,
            depth=self.depth,
        )

        context = super().get_context_data(**kwargs)
        context['flattened_categories'] = flattened_categories
        return context


class ExpenseCategoryCreateView(LoginRequiredMixin, CreateView[ExpenseCategory, Any]):
    """View for creating a new expense category."""

    model = ExpenseCategory
    template_name = 'expense/add_category_expense.html'
    form_class = AddCategoryForm
    success_url = reverse_lazy(constants.EXPENSE_CATEGORY_LIST_URL)

    def get_form_kwargs(self) -> Dict[str, Any]:
        """Get form kwargs with user-specific queryset."""
        kwargs = super().get_form_kwargs()
        if not isinstance(self.request.user, User):
            raise ValueError(constants.USER_MUST_BE_AUTHENTICATED)
        category_service = ExpenseCategoryService(self.request.user, self.request)
        kwargs['category_queryset'] = category_service.get_categories_queryset()
        return kwargs

    def form_valid(self, form: Any) -> HttpResponse:
        """Handle valid form submission."""
        if not isinstance(self.request.user, User):
            raise ValueError(constants.USER_MUST_BE_AUTHENTICATED)
        category_service = ExpenseCategoryService(self.request.user, self.request)

        try:
            category_name = self.request.POST.get('name')
            category_service.create_category(form)
            messages.success(
                self.request,
                _('Категория "{category_name}" была успешно добавлена!').format(
                    category_name=category_name,
                ),
            )
            return redirect(self.get_success_url())
        except Exception as e:
            messages.error(
                self.request,
                _('Ошибка при создании категории: {error}').format(error=str(e)),
            )
            return self.form_invalid(form)

    def form_invalid(self, form: Any) -> HttpResponse:
        """Handle invalid form submission."""
        messages.error(
            self.request,
            _('Ошибка при добавлении категории. Проверьте введенные данные.'),
        )
        return self.render_to_response(self.get_context_data(form=form))


class ExpenseCategoryDeleteView(
    DeleteObjectMixin,
    LoginRequiredMixin,
    DeleteView[ExpenseCategory, Any],
):
    """View for deleting an expense category."""

    model = ExpenseCategory
    template_name = constants.EXPENSE_CATEGORY_TEMPLATE
    success_url = reverse_lazy(constants.EXPENSE_CATEGORY_LIST_URL)
    success_message = str(constants.SUCCESS_CATEGORY_EXPENSE_DELETED)
    error_message = str(constants.ACCESS_DENIED_DELETE_EXPENSE_CATEGORY)


class ExpenseGroupAjaxView(LoginRequiredMixin, View):
    """AJAX view for getting expenses by group."""

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Handle GET request for group expenses."""
        if not isinstance(request.user, User):
            return HttpResponseForbidden(_('Вы не авторизованы'))
        group_id = request.GET.get('group_id')
        expense_service = ExpenseService(request.user, request)

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
            return HttpResponse(_('Ошибка: {error}').format(error=str(e)), status=500)


class ExpenseDataAjaxView(LoginRequiredMixin, View):
    """AJAX view for getting expense data as JSON."""

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        """Handle GET request for expense data."""
        if not isinstance(request.user, User):
            return JsonResponse({'error': _('Вы не авторизованы')}, status=403)
        group_id = request.GET.get('group_id')
        expense_service = ExpenseService(request.user, request)

        try:
            all_data = expense_service.get_expense_data(group_id)
            return JsonResponse({'data': all_data})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
