from abc import ABC, abstractmethod
from typing import Any, cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.http import (
    HttpResponse,
    HttpResponseForbidden,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView
from django.views.generic.list import ListView

from hasta_la_vista_money import constants
from hasta_la_vista_money.core.types import RequestWithContainer
from hasta_la_vista_money.core.views import (
    BaseEntityCreateView,
    BaseEntityFilterView,
    BaseEntityUpdateView,
)
from hasta_la_vista_money.custom_mixin import DeleteObjectMixin
from hasta_la_vista_money.expense.filters import ExpenseFilter
from hasta_la_vista_money.expense.forms import AddCategoryForm, AddExpenseForm
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.expense.protocols.services import (
    ExpenseServiceProtocol,
)
from hasta_la_vista_money.services.views import get_cached_category_tree
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


class ExpenseView(BaseEntityFilterView, ExpenseBaseView):
    """Main expense list view with filtering and pagination."""

    model = Expense
    context_object_name = 'expense'
    filterset_class = ExpenseFilter
    expense_service: ExpenseServiceProtocol

    @property
    def template_name(self) -> str:  # type: ignore[override]
        return constants.EXPENSE_TEMPLATE

    def get_context_data(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Get context data for expense list view.

        Returns:
            Dict containing expense data, categories, and forms.
        """
        context: dict[str, Any] = super().get_context_data(**kwargs)
        user = get_object_or_404(User, username=self.request.user)
        request = cast('RequestWithContainer', self.request)

        expense_service = request.container.expense.expense_service(
            user=user,
            request=self.request,
        )
        receipt_service = request.container.expense.receipt_expense_service(
            user=user,
            request=request,
        )

        expense_queryset = Expense.objects.select_related(
            'user',
            'category',
            'account',
        )
        expense_filter: ExpenseFilter = ExpenseFilter(
            request.GET,
            queryset=expense_queryset,
            user=request.user,
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
        flattened_categories = get_cached_category_tree(
            user_id=user.pk,
            category_type='expense',
            categories=list(expense_categories),
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
                'request': request,
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

    def post(
        self,
        request: RequestWithContainer,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponse:
        """Handle POST request to copy an expense."""
        if not isinstance(request.user, User):
            return HttpResponseForbidden(constants.USER_MUST_BE_AUTHENTICATED)
        expense_id = kwargs.get('pk')
        expense_service = request.container.expense.expense_service(
            user=request.user,
            request=request,
        )

        if expense_id is None:
            messages.error(request, _('Некорректный идентификатор расхода.'))
            return redirect(constants.EXPENSE_LIST_URL)

        try:
            new_expense = expense_service.copy_expense(int(expense_id))
            messages.success(request, _('Расход успешно скопирован.'))
            return redirect(
                str(
                    reverse_lazy(
                        'expense:change', kwargs={'pk': new_expense.pk}
                    )
                ),
            )
        except (ValueError, TypeError) as e:
            messages.error(
                request,
                _('Ошибка при копировании расхода: {error}').format(
                    error=str(e),
                ),
            )
            return redirect(constants.EXPENSE_LIST_URL)


class ExpenseCreateView(BaseEntityCreateView[Expense, AddExpenseForm]):
    """View for creating a new expense."""

    model = Expense
    template_name = 'expense/add_expense.html'
    form_class = AddExpenseForm
    success_url = reverse_lazy(constants.EXPENSE_LIST_URL)

    def get_form_kwargs(
        self,
    ) -> dict[str, Any]:
        """Get form kwargs with user-specific querysets."""
        kwargs = super().get_form_kwargs()
        if not isinstance(self.request.user, User):
            error_msg = 'User must be authenticated'
            raise TypeError(error_msg)
        request = cast('RequestWithContainer', self.request)
        expense_service = request.container.expense.expense_service(
            user=request.user,
            request=request,
        )
        kwargs.update(expense_service.get_form_querysets())
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Get context data for expense creation form."""
        context = super().get_context_data(**kwargs)
        if 'add_expense_form' not in context:
            context['add_expense_form'] = self.get_form()
        return context

    def form_valid(
        self,
        form: Any,
    ) -> HttpResponse:
        """Handle valid form submission."""
        if not isinstance(self.request.user, User):
            error_msg = 'User must be authenticated'
            raise TypeError(error_msg)
        request = cast('RequestWithContainer', self.request)
        expense_service = request.container.expense.expense_service(
            user=request.user,
            request=request,
        )

        try:
            expense = expense_service.create_expense(form)
            self.object = expense
            messages.success(self.request, constants.SUCCESS_EXPENSE_ADDED)
            return HttpResponseRedirect(self.get_success_url())
        except (ValueError, TypeError) as e:
            messages.error(
                self.request,
                _('Ошибка при создании расхода: {error}').format(error=str(e)),
            )
            return self.form_invalid(form)

    def form_invalid(self, form: Any) -> HttpResponse:
        """Handle invalid form submission."""
        return self.render_to_response(
            self.get_context_data(add_expense_form=form),
        )


class ExpenseUpdateView(BaseEntityUpdateView[Expense, AddExpenseForm]):
    """View for updating an existing expense."""

    model = Expense
    template_name = 'expense/change_expense.html'
    form_class = AddExpenseForm
    success_url = reverse_lazy(constants.EXPENSE_LIST_URL)

    def get_object(self, queryset: Any = None) -> Expense:
        """Get the expense object to update."""
        return get_object_or_404(
            Expense.objects.select_related('user', 'category', 'account'),
            pk=self.kwargs['pk'],
            user=self.request.user,
        )

    def get_form_kwargs(
        self,
    ) -> dict[str, Any]:
        """Get form kwargs with user-specific querysets."""
        kwargs = super().get_form_kwargs()
        if not isinstance(self.request.user, User):
            raise TypeError(constants.USER_MUST_BE_AUTHENTICATED)
        request = cast('RequestWithContainer', self.request)
        expense_service = request.container.expense.expense_service(
            user=request.user,
            request=request,
        )
        kwargs.update(expense_service.get_form_querysets())
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Get context data for expense update form."""
        context = super().get_context_data(**kwargs)
        context['add_expense_form'] = self.get_form()
        return context

    def form_valid(
        self,
        form: Any,
    ) -> HttpResponse:
        """Handle valid form submission."""
        if not isinstance(self.request.user, User):
            raise TypeError(constants.USER_MUST_BE_AUTHENTICATED)
        request = cast('RequestWithContainer', self.request)
        expense_service = request.container.expense.expense_service(
            user=request.user,
            request=request,
        )

        try:
            expense_service.update_expense(self.object, form)
            messages.success(self.request, constants.SUCCESS_EXPENSE_UPDATE)
            return super().form_valid(form)
        except (ValueError, TypeError) as e:
            messages.error(
                self.request,
                _('Ошибка при обновлении расхода: {error}').format(
                    error=str(e),
                ),
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

    def form_valid(
        self,
        form: Any,
    ) -> HttpResponse:
        """Handle valid form submission for deletion."""
        if not isinstance(self.request.user, User):
            raise TypeError(constants.USER_MUST_BE_AUTHENTICATED)
        request = cast('RequestWithContainer', self.request)
        expense_service = request.container.expense.expense_service(
            user=request.user,
            request=request,
        )

        try:
            expense_service.delete_expense(self.get_object())
            messages.success(self.request, constants.SUCCESS_EXPENSE_DELETED)
            return super().form_valid(form)
        except (ValueError, TypeError) as e:
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

    def get_context_data(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Get context data for category list."""
        request = cast('RequestWithContainer', self.request)
        user = get_object_or_404(User, username=request.user)
        category_service = request.container.expense.expense_category_service(
            user=user,
            request=request,
        )

        expense_categories = category_service.get_categories()
        flattened_categories = get_cached_category_tree(
            user_id=user.pk,
            category_type='expense',
            categories=list(expense_categories),
            depth=self.depth,
        )

        context = super().get_context_data(**kwargs)
        context['flattened_categories'] = flattened_categories
        return context


class ExpenseCategoryCreateView(
    LoginRequiredMixin,
    CreateView[ExpenseCategory, AddCategoryForm],
):
    """View for creating a new expense category."""

    model = ExpenseCategory
    template_name = 'expense/add_category_expense.html'
    form_class = AddCategoryForm
    success_url = reverse_lazy(constants.EXPENSE_CATEGORY_LIST_URL)

    def get_form_kwargs(
        self,
    ) -> dict[str, Any]:
        """Get form kwargs with user-specific queryset."""
        kwargs = super().get_form_kwargs()
        if not isinstance(self.request.user, User):
            raise TypeError(constants.USER_MUST_BE_AUTHENTICATED)
        request = cast('RequestWithContainer', self.request)
        category_service = request.container.expense.expense_category_service(
            user=request.user,
            request=request,
        )
        kwargs['category_queryset'] = category_service.get_categories_queryset()
        return kwargs

    def form_valid(
        self,
        form: Any,
    ) -> HttpResponse:
        """Handle valid form submission."""
        if not isinstance(self.request.user, User):
            raise TypeError(constants.USER_MUST_BE_AUTHENTICATED)
        request = cast('RequestWithContainer', self.request)
        category_service = request.container.expense.expense_category_service(
            user=request.user,
            request=request,
        )

        try:
            category_name = self.request.POST.get('name')
            self.object = category_service.create_category(form)
            messages.success(
                self.request,
                _('Категория "{category_name}" была успешно добавлена!').format(
                    category_name=category_name,
                ),
            )
            return redirect(self.get_success_url())
        except (ValueError, TypeError) as e:
            messages.error(
                self.request,
                _('Ошибка при создании категории: {error}').format(
                    error=str(e),
                ),
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
    request: RequestWithContainer
    """View for deleting an expense category."""

    model = ExpenseCategory
    template_name = constants.EXPENSE_CATEGORY_TEMPLATE
    success_url = reverse_lazy(constants.EXPENSE_CATEGORY_LIST_URL)
    success_message = str(constants.SUCCESS_CATEGORY_EXPENSE_DELETED)
    error_message = str(constants.ACCESS_DENIED_DELETE_EXPENSE_CATEGORY)


class ExpenseGroupAjaxView(LoginRequiredMixin, View):
    """AJAX view for getting expenses by group."""

    def get(
        self,
        request: RequestWithContainer,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponse:
        """Handle GET request for group expenses."""
        if not isinstance(request.user, User):
            return HttpResponseForbidden(_('Вы не авторизованы'))
        group_id = request.GET.get('group_id')
        expense_service = request.container.expense.expense_service(
            user=request.user,
            request=request,
        )

        try:
            all_expenses = expense_service.get_expenses_by_group(group_id)
            context = {'expenses': all_expenses, 'request': request}
            html = render_to_string(
                'expense/_expense_table_block.html',
                context,
                request=request,
            )
            return HttpResponse(html)
        except (ValueError, TypeError) as e:
            return HttpResponse(
                _('Ошибка: {error}').format(error=str(e)),
                status=500,
            )


class ExpenseDataAjaxView(LoginRequiredMixin, View):
    """AJAX view for getting expense data as JSON."""

    def get(
        self,
        request: RequestWithContainer,
        *args: Any,
        **kwargs: Any,
    ) -> JsonResponse:
        """Handle GET request for expense data."""
        if not isinstance(request.user, User):
            return JsonResponse({'error': _('Вы не авторизованы')}, status=403)
        group_id = request.GET.get('group_id')
        expense_service = request.container.expense.expense_service(
            user=request.user,
            request=request,
        )

        try:
            all_data = expense_service.get_expense_data(group_id)
            return JsonResponse({'data': all_data})
        except (ValueError, TypeError) as e:
            return JsonResponse({'error': str(e)}, status=500)
