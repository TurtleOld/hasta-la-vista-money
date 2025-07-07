from collections import OrderedDict
from datetime import datetime
from typing import Any, Dict, Optional

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import Group
from django.contrib.messages.views import SuccessMessageMixin
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect
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
from hasta_la_vista_money.commonlogic.views import (
    IncomeExpenseCreateViewMixin,
    build_category_tree,
    create_object_view,
    get_new_type_operation,
    get_queryset_type_income_expenses,
)
from hasta_la_vista_money.custom_mixin import (
    CustomNoPermissionMixin,
    DeleteObjectMixin,
    UpdateViewMixin,
)
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.filters import IncomeFilter
from hasta_la_vista_money.income.forms import AddCategoryIncomeForm, IncomeForm
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.users.models import User


class BaseView:
    template_name = 'income/income.html'
    success_url: Optional[str] = reverse_lazy('income:list')


class IncomeCategoryBaseView(BaseView):
    model = IncomeCategory


class IncomeView(
    CustomNoPermissionMixin,
    SuccessMessageMixin,
    BaseView,
    FilterView,
):
    """Представление просмотра доходов из модели, на сайте."""

    paginate_by = 10
    model = Income
    filterset_class = IncomeFilter
    context_object_name = 'incomes'
    no_permission_url = reverse_lazy('login')

    def get_context_data(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
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

        # Pagination removed, as Tabulator is used
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
    CustomNoPermissionMixin,
    SuccessMessageMixin,
    BaseView,
    IncomeExpenseCreateViewMixin,
):
    model = Income
    template_name = 'income/create_income.html'
    no_permission_url = reverse_lazy('login')
    form_class = IncomeForm
    depth_limit = 3
    success_url: Optional[str] = reverse_lazy('income:list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        user = get_object_or_404(User, username=self.request.user)
        income_categories = (
            IncomeCategory.objects.filter(user=user)
            .select_related('user')
            .order_by('parent_category__name', 'name')
            .all()
        )
        kwargs['category_queryset'] = income_categories
        return kwargs

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        return super().get_context_data(**kwargs)

    def form_valid(self, form: Any) -> HttpResponse:
        response_data = create_object_view(
            form=form,
            model=IncomeCategory,
            request=self.request,
            message=constants.SUCCESS_INCOME_ADDED,
        )
        if response_data.get('success'):
            return HttpResponseRedirect(str(self.success_url))
        else:
            for field, errors in response_data.get('errors', {}).items():
                if field == '__all__':
                    form.add_error(None, errors[0])
                else:
                    for error in errors:
                        form.add_error(field, error)
            return self.form_invalid(form)

    def form_invalid(self, form):
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
    CustomNoPermissionMixin,
    SuccessMessageMixin,
    BaseView,
    View,
):
    no_permission_url = reverse_lazy('login')

    def post(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        income_id = kwargs.get('pk')
        new_income = get_new_type_operation(Income, income_id, request)

        valid_income = get_object_or_404(Income, pk=new_income.pk)

        messages.success(request, _('Расход успешно скопирован.'))
        return redirect(
            reverse_lazy('income:change', kwargs={'pk': valid_income.pk}),
        )


class IncomeUpdateView(
    CustomNoPermissionMixin,
    SuccessMessageMixin,
    BaseView,
    UpdateView,
    UpdateViewMixin,
):
    model = Income
    template_name = 'income/change_income.html'
    form_class = IncomeForm
    no_permission_url = reverse_lazy('login')
    success_url: Optional[str] = reverse_lazy('income:list')
    depth_limit = 3

    def get_object(self, queryset: Any = None) -> Income:
        return get_object_or_404(
            Income,
            pk=self.kwargs['pk'],
            user=self.request.user,
        )

    def get_form_kwargs(self) -> Dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        kwargs['depth'] = self.depth_limit

        # Add category queryset for form validation
        user = get_object_or_404(User, username=self.request.user)
        income_categories = (
            IncomeCategory.objects.filter(user=user)
            .select_related('user')
            .order_by('parent_category__name', 'name')
            .all()
        )
        kwargs['category_queryset'] = income_categories

        return kwargs

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
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

    def form_valid(self, form: Any) -> HttpResponse:
        income = get_queryset_type_income_expenses(self.object.id, Income, form)

        amount = form.cleaned_data.get('amount')
        account = form.cleaned_data.get('account')
        account_balance = get_object_or_404(Account, id=account.id)
        old_account_balance = get_object_or_404(Account, id=income.account.id)

        if account_balance.user == self.request.user:
            if income:
                old_amount = income.amount
                account_balance.balance -= old_amount

            if income.account != account:
                old_account_balance.balance -= amount
                account_balance.balance += amount

            old_account_balance.save()
            account_balance.balance += amount
            account_balance.save()
            income.user = self.request.user
            income.amount = amount
            income.save()
            messages.success(
                self.request,
                constants.SUCCESS_INCOME_UPDATE,
            )
            return super().form_valid(form)
        return HttpResponseRedirect(str(self.success_url))


class IncomeDeleteView(BaseView, DeleteView, DeletionMixin):
    model = Income
    context_object_name = 'incomes'
    no_permission_url = reverse_lazy('login')
    success_url: Optional[str] = reverse_lazy('income:list')

    def form_valid(self, form: Any) -> HttpResponse:
        income = self.get_object()
        account = income.account
        amount = income.amount
        account_balance = get_object_or_404(Account, id=account.id)

        if account_balance.user == self.request.user:
            account_balance.balance -= amount
            account_balance.save()
            messages.success(
                self.request,
                constants.SUCCESS_INCOME_DELETED,
            )
            return super().form_valid(form)
        return HttpResponseRedirect(str(self.success_url))


class IncomeCategoryView(LoginRequiredMixin, ListView):
    template_name = 'income/show_category_income.html'
    model = IncomeCategory
    depth = 3

    def get_context_data(
        self,
        *,
        object_list: Any = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
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
    model = IncomeCategory
    template_name = 'income/add_category_income.html'
    form_class = AddCategoryIncomeForm
    success_url: Optional[str] = reverse_lazy('income:category_list')
    depth = 3

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        return super().get_context_data(**kwargs)

    def get_form_kwargs(self) -> Dict[str, Any]:
        kwargs = super().get_form_kwargs()
        user = get_object_or_404(User, username=self.request.user)
        categories = (
            IncomeCategory.objects.filter(user=user)
            .select_related('user')
            .order_by('parent_category__name', 'name')
            .all()
        )
        kwargs['user'] = self.request.user
        kwargs['depth'] = self.depth
        kwargs['category_queryset'] = categories
        return kwargs

    def form_valid(self, form: Any) -> HttpResponse:
        category_name = self.request.POST.get('name')
        category_form = form.save(commit=False)
        category_form.user = self.request.user
        category_form.save()
        messages.success(
            self.request,
            f'Категория "{category_name}" была успешно добавлена!',
        )

        return HttpResponseRedirect(str(self.success_url))

    def form_invalid(self, form: Any) -> HttpResponse:
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
    model = IncomeCategory
    success_message = constants.SUCCESS_CATEGORY_INCOME_DELETED
    error_message = constants.ACCESS_DENIED_DELETE_INCOME_CATEGORY
    success_url: Optional[str] = reverse_lazy('income:category_list')


class IncomeGroupAjaxView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        group_id = request.GET.get('group_id')
        user = request.user
        incomes = Income.objects.none()

        if group_id == 'my' or not group_id:
            incomes = Income.objects.filter(user=user)
        else:
            try:
                group = Group.objects.get(pk=group_id)
                users_in_group = group.user_set.all()
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
    def get(self, request, *args, **kwargs):
        group_id = request.GET.get('group_id', 'my')
        user = request.user
        incomes = Income.objects.none()

        if group_id == 'my' or not group_id:
            incomes = Income.objects.filter(user=user)
        else:
            try:
                group = Group.objects.get(pk=group_id)
                users_in_group = group.user_set.all()
                incomes = Income.objects.filter(user__in=users_in_group)
            except Group.DoesNotExist:
                incomes = Income.objects.none()

        # Подготовка данных для Tabulator
        data = []
        for income in incomes.select_related('category', 'account', 'user').all():
            data.append(
                {
                    'id': income.id,
                    'category_name': income.category.name if income.category else '',
                    'account_name': income.account.name_account
                    if income.account
                    else '',
                    'amount': float(income.amount),
                    'date': income.date.strftime('%d.%m.%Y'),
                    'user_name': income.user.username,
                    'user_id': income.user.id,
                },
            )

        # Tabulator ожидает массив данных напрямую
        return JsonResponse(data, safe=False)


class IncomeGetAjaxView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        income_id = kwargs.get('pk')
        try:
            income = Income.objects.get(id=income_id)
            # Проверяем права доступа
            if income.user != request.user:
                return JsonResponse({'success': False, 'error': 'Доступ запрещен'})

            data = {
                'success': True,
                'income': {
                    'id': income.id,
                    'date': income.date.strftime('%Y-%m-%d'),
                    'amount': float(income.amount),
                    'category_id': income.category.id if income.category else None,
                    'account_id': income.account.id if income.account else None,
                },
            }
            return JsonResponse(data)
        except Income.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Доход не найден'})
