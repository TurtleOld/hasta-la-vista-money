from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import DeleteView, UpdateView
from django.views.generic.edit import CreateView, DeletionMixin
from django.views.generic.list import ListView
from django_filters.views import FilterView
from hasta_la_vista_money import constants
from hasta_la_vista_money.commonlogic.custom_paginator import (
    paginator_custom_view,
)
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
    success_url = reverse_lazy('income:list')


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

    def get_context_data(self, *args, **kwargs):
        user = get_object_or_404(User, username=self.request.user)
        depth_limit = 3
        if user:
            categories = (
                user.category_income_users.select_related('user')
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

            income_categories = (
                user.category_income_users.select_related('user')
                .order_by('parent_category__name', 'name')
                .all()
            )
            income_form = IncomeForm(
                user=self.request.user,
                depth=depth_limit,
                category_queryset=income_categories,
            )

            income_form.fields[
                'account'
            ].queryset = user.finance_account_users.select_related(
                'user',
            ).all()

            income_by_month = income_filter.qs

            pages_income = paginator_custom_view(
                self.request,
                income_by_month,
                self.paginate_by,
                'income',
            )

            context = super().get_context_data(**kwargs)
            context['categories'] = categories
            context['income_filter'] = income_filter
            context['income_by_month'] = pages_income
            context['income_form'] = income_form
            context['flattened_categories'] = flattened_categories

            return context


class IncomeCreateView(
    CustomNoPermissionMixin,
    SuccessMessageMixin,
    BaseView,
    IncomeExpenseCreateViewMixin,
):
    model = Income
    no_permission_url = reverse_lazy('login')
    form_class = IncomeForm
    depth_limit = 3

    def form_valid(self, form):
        if form.is_valid():
            form_class = self.get_form_class()
            form = self.get_form(form_class)
            response_data = create_object_view(
                form=form,
                model=IncomeCategory,
                request=self.request,
                message=constants.SUCCESS_INCOME_ADDED,
            )
            return JsonResponse(response_data)


class IncomeCopyView(
    CustomNoPermissionMixin,
    SuccessMessageMixin,
    BaseView,
    View,
):
    no_permission_url = reverse_lazy('login')

    def post(self, request, *args, **kwargs):
        income_id = kwargs.get('pk')
        new_income = get_new_type_operation(Income, income_id, request)

        messages.success(request, 'Расход успешно скопирован.')
        return redirect(
            reverse_lazy('income:change', kwargs={'pk': new_income.pk}),
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
    success_url = reverse_lazy('income:list')
    depth_limit = 3

    def get_object(self, queryset=None):
        return get_object_or_404(
            Income,
            pk=self.kwargs['pk'],
            user=self.request.user,
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        kwargs['depth'] = self.depth_limit
        return kwargs

    def get_context_data(self, **kwargs):
        user = get_object_or_404(User, username=self.request.user)
        context = super().get_context_data(**kwargs)
        form_class = self.get_form_class()
        form = form_class(**self.get_form_kwargs())
        form.fields['account'].queryset = user.finance_account_users.select_related(
            'user',
        ).all()
        context['income_form'] = form
        return context

    def form_valid(self, form):
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


class IncomeDeleteView(BaseView, DeleteView, DeletionMixin):
    model = Income
    context_object_name = 'incomes'
    no_permission_url = reverse_lazy('login')

    def form_valid(self, form):
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


class IncomeCategoryView(ListView):
    template_name = 'income/show_category_income.html'
    model = IncomeCategory
    depth = 3

    def get_context_data(self, *, object_list=..., **kwargs):
        user = get_object_or_404(User, username=self.request.user)
        categories = (
            user.category_income_users.select_related('user')
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
        context['categories'] = categories
        context['flattened_categories'] = flattened_categories

        return context


class IncomeCategoryCreateView(CreateView):
    model = IncomeCategory
    template_name = 'income/add_category_income.html'
    form_class = AddCategoryIncomeForm
    success_url = reverse_lazy('income:category_list')
    depth = 3

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        add_category_income_form = AddCategoryIncomeForm(
            user=self.request.user,
            depth=self.depth,
        )
        context['add_category_income_form'] = add_category_income_form
        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        kwargs['depth'] = self.depth
        return kwargs

    def form_valid(self, form):
        category_name = self.request.POST.get('name')
        category_form = form.save(commit=False)
        category_form.user = self.request.user
        category_form.save()
        messages.success(
            self.request,
            f'Категория "{category_name}" была успешно добавлена!',
        )

        return redirect(self.success_url)

    def form_invalid(self, form):
        error_message = ''
        if 'name' in form.errors:
            error_message = 'Такая категория уже была добавлена!'
        else:
            error_message = (
                'Ошибка при добавлении категории. Проверьте введенные данные.'
            )
        messages.error(self.request, error_message)

        return HttpResponseRedirect(reverse_lazy('income:create_category'))


class IncomeCategoryDeleteView(BaseView, DeleteObjectMixin):
    model = IncomeCategory
    success_message = constants.SUCCESS_CATEGORY_INCOME_DELETED
    error_message = constants.ACCESS_DENIED_DELETE_INCOME_CATEGORY
