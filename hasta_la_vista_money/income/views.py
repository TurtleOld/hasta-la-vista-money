from collections import OrderedDict
from datetime import datetime
from typing import Any, Dict, Optional

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import Group
from django.contrib.messages.views import SuccessMessageMixin
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.utils import formats
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import DeleteView, UpdateView
from django.views.generic.edit import CreateView, DeletionMixin
from django.views.generic.list import ListView
from django_filters.views import FilterView
from hasta_la_vista_money import constants
from hasta_la_vista_money.custom_mixin import DeleteObjectMixin
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.filters import IncomeFilter
from hasta_la_vista_money.income.forms import AddCategoryIncomeForm, IncomeForm
from hasta_la_vista_money.income.mixins import IncomeFormQuerysetMixin
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.services import income as income_services
from hasta_la_vista_money.services.views import build_category_tree
from hasta_la_vista_money.users.models import User

INCOME_LIST_URL_NAME = 'income:list'


class BaseView:
    """
    Base view for income-related views. Sets default template and success_url.
    """

    template_name = 'income/income.html'
    success_url: Optional[str] = reverse_lazy(INCOME_LIST_URL_NAME)


class IncomeCategoryBaseView(BaseView):
    """
    Base view for income category-related views.
    """

    model = IncomeCategory


class IncomeView(
    LoginRequiredMixin,
    SuccessMessageMixin,
    BaseView,
    FilterView,
):
    """
    View for displaying user's incomes with filtering and chart data.
    """

    paginate_by = 10
    model = Income
    filterset_class = IncomeFilter
    context_object_name = 'incomes'
    no_permission_url = reverse_lazy('login')

    def get_context_data(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """
        Build context for income list, including categories, filters, and chart data.
        """
        context = super().get_context_data(**kwargs)
        user = get_object_or_404(User, username=self.request.user)
        depth_limit = 3

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

        income_filter = IncomeFilter(
            self.request.GET,
            queryset=Income.objects.all(),
            user=self.request.user,
        )

        flattened_categories = build_category_tree(
            categories,
            depth=depth_limit,
        )

        income_by_month = income_filter.qs

        pages_income = income_by_month

        total_amount_page = sum(income['amount'] for income in pages_income)
        total_amount_period = sum(income['amount'] for income in income_by_month)

        monthly_data = OrderedDict()
        sorted_incomes = sorted(income_by_month, key=lambda x: x['date'])
        for income in sorted_incomes:
            date_val = income['date']
            if isinstance(date_val, str):
                try:
                    date_val = datetime.fromisoformat(date_val)
                except ValueError:
                    # Пропускаем записи с некорректным форматом даты
                    continue
            month_label = formats.date_format(date_val, 'F Y')
            if month_label not in monthly_data:
                monthly_data[month_label] = 0
            monthly_data[month_label] += income['amount']
        chart_labels = list(monthly_data.keys())
        chart_values = [float(v) for v in monthly_data.values()]

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
    LoginRequiredMixin,
    SuccessMessageMixin,
    IncomeFormQuerysetMixin,
    BaseView,
    CreateView,
):
    """
    View for creating a new income record.
    """

    model = Income
    template_name = 'income/create_income.html'
    no_permission_url = reverse_lazy('login')
    form_class = IncomeForm
    depth_limit = 3
    success_url: Optional[str] = reverse_lazy(INCOME_LIST_URL_NAME)

    category_model = IncomeCategory
    account_model = Account

    def get_form_kwargs(self):
        """
        Provide form kwargs with user-specific category and account querysets.
        """
        kwargs = super().get_form_kwargs()
        kwargs['category_queryset'] = self.get_category_queryset()
        kwargs['account_queryset'] = self.get_account_queryset()
        return kwargs

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        """
        Build context for income creation form.
        """
        return super().get_context_data(**kwargs)

    def form_valid(self, form: Any) -> HttpResponse:
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

        try:
            income_services.add_income(
                self.request.user,
                account,
                category,
                amount,
                date,
            )
            messages.success(self.request, constants.SUCCESS_INCOME_ADDED)
            return HttpResponseRedirect(str(self.success_url))
        except Exception as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)

    def form_invalid(self, form):
        """
        Handle invalid form submission for income creation.
        """
        user = get_object_or_404(User, username=self.request.user)
        income_categories = (
            IncomeCategory.objects.filter(user=user)
            .select_related('user')
            .order_by('parent_category__name', 'name')
            .all()
        )
        form.fields['category'].queryset = income_categories
        return self.render_to_response(self.get_context_data(form=form))


class IncomeCopyView(
    LoginRequiredMixin,
    SuccessMessageMixin,
    BaseView,
    View,
):
    """
    View for copying an existing income record.
    """

    no_permission_url = reverse_lazy('login')

    def post(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        """
        Handle POST request to copy an income record.
        """
        income_id = kwargs.get('pk')
        try:
            income_services.copy_income(request.user, income_id)
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})


class IncomeUpdateView(
    LoginRequiredMixin,
    SuccessMessageMixin,
    IncomeFormQuerysetMixin,
    BaseView,
    UpdateView,
):
    """
    View for updating an existing income record.
    """

    model = Income
    template_name = 'income/change_income.html'
    form_class = IncomeForm
    no_permission_url = reverse_lazy('login')
    success_url: Optional[str] = reverse_lazy(INCOME_LIST_URL_NAME)
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

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        """
        Build context for income update form.
        """
        user = get_object_or_404(User, username=self.request.user)
        context = super().get_context_data(**kwargs)

        income_categories = (
            IncomeCategory.objects.filter(user=user)
            .select_related('user')
            .order_by('parent_category__name', 'name')
            .all()
        )

        form_class = self.get_form_class()
        form_kwargs = self.get_form_kwargs()
        form_kwargs['category_queryset'] = income_categories
        form = form_class(**form_kwargs)
        context['income_form'] = form
        return context

    def get_form_kwargs(self) -> dict:
        """
        Provide form kwargs with user-specific category and account querysets for update.
        """
        kwargs = super().get_form_kwargs()
        kwargs['category_queryset'] = self.get_category_queryset()
        kwargs['account_queryset'] = self.get_account_queryset()
        return kwargs

    def form_valid(self, form: Any) -> HttpResponse:
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
            income_services.update_income(
                self.request.user,
                income,
                account,
                category,
                amount,
                date,
            )
            messages.success(self.request, constants.SUCCESS_INCOME_UPDATE)
            return super().form_valid(form)
        except Exception as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)


class IncomeDeleteView(BaseView, DeleteView, DeletionMixin):
    """
    View for deleting an income record.
    """

    model = Income
    context_object_name = 'incomes'
    no_permission_url = reverse_lazy('login')
    success_url: Optional[str] = reverse_lazy(INCOME_LIST_URL_NAME)

    def post(self, request, *args, **kwargs):
        """
        Handle POST request to delete an income record.
        """
        income = self.get_object()
        try:
            income_services.delete_income(request.user, income)
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})


class IncomeCategoryView(LoginRequiredMixin, ListView):
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
    ) -> Dict[str, Any]:
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
        flattened_categories = build_category_tree(
            categories,
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


class IncomeCategoryCreateView(LoginRequiredMixin, CreateView):
    """
    View for creating a new income category.
    """

    model = IncomeCategory
    template_name = 'income/add_category_income.html'
    form_class = AddCategoryIncomeForm
    success_url: Optional[str] = reverse_lazy('income:category_list')
    depth = 3

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        """
        Build context for income category creation form.
        """
        return super().get_context_data(**kwargs)

    def get_form_kwargs(self) -> Dict[str, Any]:
        """
        Provide form kwargs with user-specific category queryset for category creation.
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
            _('Category "%(name)s" was successfully added!') % {'name': category_name},
        )

        return HttpResponseRedirect(str(self.success_url))

    def form_invalid(self, form: Any) -> HttpResponse:
        """
        Handle invalid form submission for income category creation.
        """
        error_message = ''
        if 'name' in form.errors:
            error_message = _('Такая категория уже была добавлена!')
        else:
            error_message = _(
                'Ошибка при добавлении категории. Проверьте введенные данные.',
            )
        messages.error(self.request, error_message)
        return self.render_to_response(self.get_context_data(form=form))


class IncomeCategoryDeleteView(BaseView, DeleteObjectMixin):
    """
    View for deleting an income category.
    """

    model = IncomeCategory
    success_message = constants.SUCCESS_CATEGORY_INCOME_DELETED
    error_message = constants.ACCESS_DENIED_DELETE_INCOME_CATEGORY
    success_url: Optional[str] = reverse_lazy('income:category_list')


class IncomeGroupAjaxView(LoginRequiredMixin, View):
    """
    AJAX view for retrieving incomes by group.
    """

    def get(self, request, *args, **kwargs):
        """
        Handle GET request to retrieve incomes by group for AJAX.
        """
        group_id = request.GET.get('group_id')
        user = request.user
        incomes = Income.objects.none()

        if group_id == 'my' or not group_id:
            incomes = Income.objects.filter(user=user)
        else:
            try:
                group = Group.objects.get(pk=group_id)
                users_in_group = User.objects.filter(groups=group)
                incomes = Income.objects.filter(user__in=users_in_group)
            except Group.DoesNotExist:
                incomes = Income.objects.none()

        context = {
            'income_by_month': incomes,
            'request': request,
        }
        html = render_to_string('income/_income_table_block.html', context)
        return HttpResponse(html)


class IncomeDataAjaxView(LoginRequiredMixin, View):
    """
    AJAX view for retrieving income data for Tabulator.
    """

    def get(self, request, *args, **kwargs):
        """
        Handle GET request to retrieve income data for AJAX.
        """
        group_id = request.GET.get('group_id', 'my')
        user = request.user
        incomes = Income.objects.none()

        if group_id == 'my' or not group_id:
            incomes = Income.objects.filter(user=user)
        else:
            try:
                group = Group.objects.get(pk=group_id)
                users_in_group = User.objects.filter(groups=group)
                incomes = Income.objects.filter(user__in=users_in_group)
            except Group.DoesNotExist:
                incomes = Income.objects.none()

        data = []
        for income in incomes.select_related('category', 'account', 'user').all():
            data.append(
                {
                    'id': income.pk,
                    'category_name': income.category.name if income.category else '',
                    'account_name': income.account.name_account
                    if income.account
                    else '',
                    'amount': float(income.amount),
                    'date': income.date.strftime('%d.%m.%Y'),
                    'user_name': income.user.username,
                    'user_id': income.user.pk,
                },
            )

        return JsonResponse(data, safe=False)


class IncomeGetAjaxView(LoginRequiredMixin, View):
    """
    AJAX view for retrieving a single income record by ID.
    """

    def get(self, request, *args, **kwargs):
        """
        Handle GET request to retrieve a single income record for AJAX.
        """
        income_id = kwargs.get('pk')
        try:
            income = Income.objects.get(id=income_id)
            # Проверяем права доступа
            if income.user != request.user:
                return JsonResponse({'success': False, 'error': 'Доступ запрещен'})

            data = {
                'success': True,
                'income': {
                    'id': income.pk,
                    'date': income.date.strftime('%Y-%m-%d'),
                    'amount': float(income.amount),
                    'category_id': income.category.id if income.category else None,
                    'account_id': income.account.id if income.account else None,
                },
            }
            return JsonResponse(data)
        except Income.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Доход не найден'})
