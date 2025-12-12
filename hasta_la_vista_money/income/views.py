from collections import OrderedDict
from typing import Any, Literal, TypedDict, cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import PermissionDenied
from django.db.models.aggregates import Sum
from django.db.models.functions import TruncMonth
from django.http import (
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.utils import formats
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import DeleteView
from django.views.generic.edit import CreateView
from django.views.generic.list import ListView
from django_stubs_ext import StrOrPromise

from hasta_la_vista_money import constants
from hasta_la_vista_money.core.mixins import (
    EntityListViewMixin,
    FormErrorHandlingMixin,
    UserAuthMixin,
)
from hasta_la_vista_money.core.types import RequestWithContainer
from hasta_la_vista_money.core.views import (
    BaseEntityCreateView,
    BaseEntityFilterView,
    BaseEntityUpdateView,
)
from hasta_la_vista_money.custom_mixin import DeleteObjectMixin
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.filters import IncomeFilter
from hasta_la_vista_money.income.forms import AddCategoryIncomeForm, IncomeForm
from hasta_la_vista_money.income.mixins import IncomeFormQuerysetMixin
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.services.views import get_cached_category_tree
from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.users.views import AuthRequest

INCOME_LIST_URL_NAME = 'income:list'


class IncomeTyped(TypedDict):
    pk: int
    date: str
    amount: float
    category_id: int
    account_id: int


class SuccessResponseTyped(TypedDict):
    success: Literal[True]
    income: IncomeTyped


class ErrorResponseTyped(TypedDict):
    success: Literal[False]
    error: str


class BaseView:
    """
    Base view for income-related views. Sets default template and success_url.
    """

    def get_success_url(self) -> str | StrOrPromise | None:
        return reverse_lazy(INCOME_LIST_URL_NAME)

    def get_template_name(self) -> str | None:
        return 'income/income.html'


class IncomeCategoryBaseView(BaseView):
    """
    Base view for income category-related views.
    """

    model = IncomeCategory


class IncomeView(BaseEntityFilterView, BaseView, EntityListViewMixin):
    """
    View for displaying user's incomes with filtering and chart data.
    """

    model = Income
    filterset_class = IncomeFilter
    template_name = 'income/income.html'
    context_object_name = 'incomes'

    def get_context_data(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """
        Build context for income list, including categories, filters,
        and chart data.
        """
        context = super().get_context_data(**kwargs)
        self.get_request_with_container()
        user = self.get_current_user()
        depth_limit = 3

        categories = (
            IncomeCategory.objects.filter(user=user)
            .select_related('user', 'parent_category')
            .values(
                'id',
                'name',
                'parent_category',
                'parent_category__name',
            )
            .order_by('parent_category_id')
        )

        income_queryset = Income.objects.select_related(
            'user',
            'category',
            'account',
        )
        income_filter = self.get_filtered_queryset(
            IncomeFilter,
            income_queryset,
        )

        flattened_categories = self.get_flattened_categories(
            categories,
            category_type='income',
            depth=depth_limit,
        )

        income_by_month = income_filter.qs.values('date', 'amount')
        pages_income = income_by_month

        total_amount_page = self.get_total_amount_value(
            income_by_month,
            amount_field='amount',
        )
        total_amount_period = total_amount_page

        monthly_aggregation = (
            income_filter.qs.annotate(month=TruncMonth('date'))
            .values('month')
            .annotate(total=Sum('amount'))
            .order_by('month')
        )

        monthly_data = OrderedDict()
        for item in monthly_aggregation:
            month_date = item['month']
            month_label = formats.date_format(month_date, 'F Y')
            monthly_data[month_label] = float(item['total'] or 0)

        chart_labels = list(monthly_data.keys())
        chart_values = list(monthly_data.values())

        context.update(
            {
                'categories': categories,
                'income_filter': income_filter,
                'income_by_month': pages_income,
                'flattened_categories': flattened_categories,
                'total_amount_page': total_amount_page,
                'total_amount_period': total_amount_period,
                'chart_labels': chart_labels,
                'chart_values': chart_values,
            },
        )

        return context


class IncomeCreateView(
    BaseEntityCreateView[Income, IncomeForm],
    IncomeFormQuerysetMixin,
    BaseView,
    UserAuthMixin,
    FormErrorHandlingMixin,
):
    """
    View for creating a new income record.
    """

    model = Income
    template_name = 'income/create_income.html'
    form_class = IncomeForm
    depth_limit = 3
    success_url = reverse_lazy(INCOME_LIST_URL_NAME)

    category_model = IncomeCategory
    account_model = Account

    def get_form_kwargs(self) -> dict[str, Any]:
        """
        Provide form kwargs with user-specific category and account querysets.
        """
        kwargs = super().get_form_kwargs()
        kwargs['category_queryset'] = self.get_category_queryset()
        kwargs['account_queryset'] = self.get_account_queryset()
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """
        Build context for income creation form.
        """
        return super().get_context_data(**kwargs)

    def form_valid(
        self,
        form: Any,
    ) -> HttpResponse:
        """
        Handle valid form submission for income creation.
        """
        if not form.is_valid():
            return self.form_invalid(form)

        cd = form.cleaned_data
        amount = cd.get('amount')
        account = cd.get('account')
        category = cd.get('category')
        date = cd.get('date')

        if not all([amount, account, category, date]):
            form.add_error(None, _('All fields must be filled.'))
            return self.form_invalid(form)

        request = cast('RequestWithContainer', self.request)
        try:
            income_ops = request.container.income.income_ops()
            income_ops.add_income(
                user=request.user,
                account=account,
                category=category,
                amount=amount,
                when=date,
            )
            messages.success(request, constants.SUCCESS_INCOME_ADDED)
            return HttpResponseRedirect(str(self.success_url))
        except (ValueError, TypeError, PermissionDenied) as e:
            return self.handle_form_error_with_field_error(form, e)

    def form_invalid(self, form: Any) -> HttpResponse:
        """
        Handle invalid form submission for income creation.
        """
        context = self.get_context_data(form=form)
        if 'categories' in context:
            form.fields['category'].queryset = context['categories']
        return self.render_to_response(context)


class IncomeCopyView(
    LoginRequiredMixin,
    SuccessMessageMixin[IncomeForm],
    BaseView,
    View,
    UserAuthMixin,
    FormErrorHandlingMixin,
):
    """
    View for copying an existing income record.
    """

    no_permission_url = reverse_lazy('login')

    def post(
        self,
        request: RequestWithContainer,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponse:
        """
        Handle POST request to copy an income record.
        """
        income_id = kwargs.get('pk')
        if income_id is None:
            return JsonResponse(
                {'success': False, 'error': 'Income ID is required'},
            )
        try:
            income_ops = request.container.income.income_ops()
            income_ops.copy_income(user=request.user, income_id=int(income_id))
            return JsonResponse({'success': True})
        except (ValueError, TypeError, PermissionDenied) as e:
            return self.handle_ajax_error_with_success_flag(e)


class IncomeUpdateView(
    BaseEntityUpdateView[Income, IncomeForm],
    IncomeFormQuerysetMixin,
    BaseView,
    UserAuthMixin,
    FormErrorHandlingMixin,
):
    """
    View for updating an existing income record.
    """

    model = Income
    template_name = 'income/change_income.html'
    form_class = IncomeForm
    success_url = reverse_lazy(INCOME_LIST_URL_NAME)
    depth_limit = 3

    category_model = IncomeCategory
    account_model = Account

    def get_object(self, queryset: Any = None) -> Income:
        """
        Get the income object for update, ensuring it belongs to the user.
        """
        return get_object_or_404(
            Income,
            pk=self.kwargs['pk'],
            user=self.request.user,
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """
        Build context for income update form.
        """
        request = cast('RequestWithContainer', self.request)
        user = get_object_or_404(User, username=request.user)
        context = super().get_context_data(**kwargs)

        income_categories = (
            IncomeCategory.objects.filter(user=user)
            .select_related('user', 'parent_category')
            .order_by('parent_category__name', 'name')
        )

        form_class = self.get_form_class()
        form_kwargs = self.get_form_kwargs()
        form_kwargs['category_queryset'] = income_categories
        form = form_class(**form_kwargs)
        context['income_form'] = form
        context['cancel_url'] = (
            str(self.success_url)
            if self.success_url
            else reverse_lazy('income:list')
        )
        return context

    def get_form_kwargs(self) -> dict[str, Any]:
        """
        Provide form kwargs with user-specific category and account
        querysets for update.
        """
        kwargs = super().get_form_kwargs()
        kwargs['category_queryset'] = self.get_category_queryset()
        kwargs['account_queryset'] = self.get_account_queryset()
        return kwargs

    def form_valid(
        self,
        form: Any,
    ) -> HttpResponse:
        """
        Handle valid form submission for income update.
        """
        income = self.get_object()
        cd = form.cleaned_data
        amount = cd.get('amount')
        account = cd.get('account')
        category = cd.get('category')
        date = cd.get('date')
        try:
            request = cast('RequestWithContainer', self.request)
            income_ops = request.container.income.income_ops()
            income_ops.update_income(
                user=request.user,
                income=income,
                account=account,
                category=category,
                amount=amount,
                when=date,
            )
            messages.success(request, constants.SUCCESS_INCOME_UPDATE)
            return super().form_valid(form)
        except (ValueError, TypeError, PermissionDenied) as e:
            return self.handle_form_error_with_field_error(form, e)


class IncomeDeleteView(
    LoginRequiredMixin,
    DeleteView[Income, IncomeForm],
    BaseView,
    UserAuthMixin,
    FormErrorHandlingMixin,
):
    """
    View for deleting an income record.
    """

    model = Income
    context_object_name = 'incomes'
    no_permission_url = reverse_lazy('login')
    success_url = reverse_lazy(INCOME_LIST_URL_NAME)

    def post(  # type: ignore[override]
        self,
        request: RequestWithContainer,
        *args: object,
        **kwargs: object,
    ) -> JsonResponse:
        """
        Handle POST request to delete an income record.
        """
        income = self.get_object()
        try:
            income_ops = request.container.income.income_ops()
            income_ops.delete_income(user=request.user, income=income)
            return JsonResponse({'success': True})
        except (ValueError, TypeError, PermissionDenied) as e:
            return self.handle_ajax_error_with_success_flag(e)


class IncomeCategoryView(LoginRequiredMixin, ListView[IncomeCategory]):
    """
    View for displaying income categories in a hierarchical structure.
    """

    template_name = 'income/show_category_income.html'
    model = IncomeCategory
    depth = 3

    def get_context_data(
        self,
        *,
        object_list: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Build context for income category list view.
        """
        user = get_object_or_404(User, username=self.request.user)
        categories = (
            IncomeCategory.objects.filter(user=user)
            .select_related('user')
            .values(
                'id',
                'name',
                'parent_category',
                'parent_category__name',
            )
            .order_by('parent_category_id')
            .all()
        )
        flattened_categories = get_cached_category_tree(
            user_id=user.pk,
            category_type='income',
            categories=[dict(cat) for cat in categories],
            depth=self.depth,
        )
        context = super().get_context_data(**kwargs)
        context.update(
            {
                'categories': categories,
                'flattened_categories': flattened_categories,
            },
        )
        return context


class IncomeCategoryCreateView(
    LoginRequiredMixin,
    CreateView[IncomeCategory, AddCategoryIncomeForm],
):
    """
    View for creating a new income category.
    """

    model = IncomeCategory
    template_name = 'income/add_category_income.html'
    form_class = AddCategoryIncomeForm
    success_url = reverse_lazy('income:category_list')
    depth = 3

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """
        Build context for income category creation form.
        """
        return super().get_context_data(**kwargs)

    def get_form_kwargs(self) -> dict[str, Any]:
        """
        Provide form kwargs with user-specific category queryset for
        category creation.
        """
        kwargs = super().get_form_kwargs()
        user = get_object_or_404(User, username=self.request.user)
        categories = (
            IncomeCategory.objects.filter(user=user)
            .select_related('user')
            .order_by('parent_category__name', 'name')
            .all()
        )
        kwargs['category_queryset'] = categories
        return kwargs

    def form_valid(self, form: Any) -> HttpResponse:
        """
        Handle valid form submission for income category creation.
        """
        category_name = self.request.POST.get('name')
        category_form = form.save(commit=False)
        category_form.user = self.request.user
        category_form.save()
        messages.success(
            self.request,
            _('Category "%(name)s" was successfully added!')
            % {'name': category_name},
        )

        return HttpResponseRedirect(str(self.success_url))

    def form_invalid(self, form: Any) -> HttpResponse:
        """
        Handle invalid form submission for income category creation.
        """
        error_message: str
        if 'name' in form.errors:
            error_message = str(_('Такая категория уже была добавлена!'))
        else:
            error_message = str(
                _(
                    'Ошибка при добавлении категории. '
                    'Проверьте введенные данные.',
                ),
            )
        messages.error(self.request, error_message)
        return self.render_to_response(self.get_context_data(form=form))


class IncomeCategoryDeleteView(
    DeleteObjectMixin,
    DeleteView[IncomeCategory, AddCategoryIncomeForm],
    BaseView,
):
    """
    View for deleting an income category.
    """

    model = IncomeCategory
    success_message = str(constants.SUCCESS_CATEGORY_INCOME_DELETED)
    error_message = str(constants.ACCESS_DENIED_DELETE_INCOME_CATEGORY)
    success_url = reverse_lazy('income:category_list')


