from collections import namedtuple
from typing import Any, Optional

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import Group
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Sum
from django.db.models.functions import ExtractYear, TruncMonth
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.utils.formats import date_format
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, UpdateView
from django.views.generic.list import ListView
from django_filters.views import FilterView
from hasta_la_vista_money import constants
from hasta_la_vista_money.commonlogic.custom_paginator import (
    paginator_custom_view,
)
from hasta_la_vista_money.commonlogic.views import (
    IncomeExpenseCreateViewMixin,
    build_category_tree,
    get_new_type_operation,
    get_queryset_type_income_expenses,
)
from hasta_la_vista_money.custom_mixin import (
    CustomNoPermissionMixin,
    DeleteObjectMixin,
    UpdateViewMixin,
)
from hasta_la_vista_money.expense.filters import ExpenseFilter
from hasta_la_vista_money.expense.forms import AddCategoryForm, AddExpenseForm
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.users.models import User


class BaseView:
    template_name = 'expense/show_expense.html'
    success_url: Optional[str] = reverse_lazy('expense:list')


class ExpenseBaseView(BaseView):
    model = Expense


class ExpenseCategoryBaseView(BaseView):
    model = ExpenseCategory


class ExpenseView(
    CustomNoPermissionMixin,
    ExpenseBaseView,
    SuccessMessageMixin,
    FilterView,
):
    paginate_by = 10
    context_object_name = 'expense'
    filterset_class = ExpenseFilter
    no_permission_url = reverse_lazy('login')

    def get_context_data(self, *args, **kwargs) -> dict[str, Any]:
        """
        Метод отображения расходов по месяцам на странице.

        :return: Рендеринг данных на странице сайта.
        """
        context = super().get_context_data(**kwargs)
        user = get_object_or_404(User, username=self.request.user)
        depth_limit = 3

        # Get receipt expense category if it exists
        receipt_category = ExpenseCategory.objects.filter(
            user=user,
            name='Покупки по чекам',
        ).first()

        expense_categories = (
            user.category_expense_users.select_related('user')
            .values(
                'id',
                'name',
                'parent_category',
                'parent_category__name',
            )
            .order_by('name', 'parent_category')
            .all()
        )
        expense_filter = ExpenseFilter(
            self.request.GET,
            queryset=Expense.objects.all(),
            user=self.request.user,
        )
        flattened_categories = build_category_tree(
            expense_categories,
            depth=depth_limit,
        )
        categories = (
            user.category_expense_users.select_related('user')
            .order_by('parent_category__name', 'name')
            .all()
        )
        add_expense_form = AddExpenseForm(
            user=self.request.user,
            depth=depth_limit,
            category_queryset=categories,
        )

        expenses = expense_filter.qs.select_related(
            'user',
            'category',
            'account',
        ).order_by('-date')

        ReceiptExpense = namedtuple(
            'ReceiptExpense',
            [
                'id',
                'date',
                'amount',
                'category',
                'account',
                'user',
                'is_receipt',
                'date_label',
            ],
        )
        receipt_expenses = (
            Receipt.objects.filter(
                user=user,
                operation_type=1,
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
        receipt_expense_list = []
        if receipt_category:  # Only process receipts if category exists
            for receipt in receipt_expenses:
                month_date = receipt['month']
                date_label = date_format(month_date, 'F Y')
                category_obj = receipt_category
                account_obj = type(
                    'AccountObj',
                    (),
                    {'name_account': receipt['account__name_account']},
                )()
                receipt_expense_list.append(
                    ReceiptExpense(
                        id=f'receipt_{month_date.year}{month_date.strftime("%m")}_{receipt["account__name_account"]}',
                        date=month_date,
                        amount=receipt['total_sum'],
                        category=category_obj,
                        account=account_obj,
                        user=user,
                        is_receipt=True,
                        date_label=date_label,
                    ),
                )

        all_expenses = list(expenses) + receipt_expense_list

        pages_expense = paginator_custom_view(
            self.request,
            all_expenses,
            self.paginate_by,
            'expenses',
        )

        total_amount_page = sum(
            getattr(income, 'amount', 0) for income in pages_expense
        )
        total_amount_period = sum(
            getattr(income, 'amount', 0) for income in all_expenses
        )

        context['expense_filter'] = expense_filter
        context['categories'] = expense_categories
        context['expenses'] = pages_expense
        context['add_expense_form'] = add_expense_form
        context['flattened_categories'] = flattened_categories
        context['total_amount_page'] = total_amount_page
        context['total_amount_period'] = total_amount_period
        context['request'] = self.request

        return context


class ExpenseCopyView(
    CustomNoPermissionMixin,
    SuccessMessageMixin,
    ExpenseBaseView,
    View,
):
    no_permission_url = reverse_lazy('login')

    def post(self, request, *args, **kwargs):
        expense_id = kwargs.get('pk')
        new_expense = get_new_type_operation(Expense, expense_id, request)

        valid_expense = get_object_or_404(Expense, pk=new_expense.pk)

        messages.success(request, 'Расход успешно скопирован.')
        return redirect(
            reverse_lazy('expense:change', kwargs={'pk': valid_expense.pk}),
        )


class ExpenseCreateView(
    CustomNoPermissionMixin,
    SuccessMessageMixin,
    ExpenseBaseView,
    IncomeExpenseCreateViewMixin,
):
    no_permission_url = reverse_lazy('login')
    template_name = 'expense/add_expense.html'
    form_class = AddExpenseForm
    depth_limit = 3
    success_url: Optional[str] = reverse_lazy('expense:list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        user = self.request.user
        categories = (
            ExpenseCategory.objects.filter(user=user)
            .order_by('parent_category__name', 'name')
            .all()
        )
        kwargs['category_queryset'] = categories
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if 'add_expense_form' not in context:
            context['add_expense_form'] = self.get_form()
        return context

    def form_valid(self, form):
        expense = form.save(commit=False)
        expense.user = self.request.user
        expense.save()
        messages.success(self.request, constants.SUCCESS_EXPENSE_ADDED)
        return super().form_valid(form)

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(add_expense_form=form))


class ExpenseUpdateView(
    CustomNoPermissionMixin,
    SuccessMessageMixin,
    ExpenseBaseView,
    UpdateView,
    UpdateViewMixin,
):
    template_name = 'expense/change_expense.html'
    form_class = AddExpenseForm
    no_permission_url = reverse_lazy('login')

    def get_object(self, queryset=None):
        return get_object_or_404(
            Expense,
            pk=self.kwargs['pk'],
            user=self.request.user,
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        kwargs['depth'] = self.depth_limit

        # Add category queryset for form validation
        user = get_object_or_404(User, username=self.request.user)
        categories = (
            user.category_expense_users.select_related('user')
            .order_by('parent_category__name', 'name')
            .all()
        )
        kwargs['category_queryset'] = categories

        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = self.get_form()
        context['add_expense_form'] = form
        return context

    def form_valid(self, form):
        expense = get_queryset_type_income_expenses(
            self.object.id,
            Expense,
            form,
        )

        amount = form.cleaned_data.get('amount')
        account = form.cleaned_data.get('account')
        account_balance = get_object_or_404(Account, id=account.id)
        old_account_balance = get_object_or_404(Account, id=expense.account.id)

        if account_balance.user == self.request.user:
            if expense:
                old_amount = expense.amount
                account_balance.balance += old_amount

            if expense.account != account:
                old_account_balance.balance += amount
                account_balance.balance -= amount

            old_account_balance.save()
            account_balance.balance -= amount
            account_balance.save()

            expense.user = self.request.user
            expense.amount = amount
            expense.save()

            messages.success(
                self.request,
                constants.SUCCESS_EXPENSE_UPDATE,
            )
            return super().form_valid(form)


class ExpenseDeleteView(LoginRequiredMixin, ExpenseBaseView, DetailView, DeleteView):
    context_object_name = 'expense'
    no_permission_url = reverse_lazy('login')

    def form_valid(self, form):
        expense = self.get_object()
        account = expense.account
        amount = expense.amount
        account_balance = get_object_or_404(Account, id=account.id)

        if account_balance.user == self.request.user:
            account_balance.balance += amount
            account_balance.save()
            messages.success(
                self.request,
                constants.SUCCESS_EXPENSE_DELETED,
            )
            return super().form_valid(form)


class ExpenseCategoryView(LoginRequiredMixin, ListView):
    template_name = 'expense/show_category_expense.html'
    model = ExpenseCategory
    depth = 3

    def get_context_data(self, **kwargs) -> dict[str, Any]:
        user = get_object_or_404(User, username=self.request.user)
        expense_categories = (
            user.category_expense_users.select_related('user')
            .values(
                'id',
                'name',
                'parent_category',
                'parent_category__name',
            )
            .order_by('name', 'parent_category')
            .all()
        )
        flattened_categories = build_category_tree(
            expense_categories,
            depth=self.depth,
        )
        context = super().get_context_data(**kwargs)

        context['flattened_categories'] = flattened_categories

        return context


class ExpenseCategoryCreateView(LoginRequiredMixin, CreateView):
    model = ExpenseCategory
    template_name = 'expense/add_category_expense.html'
    form_class = AddCategoryForm
    depth = 3
    success_url: str = reverse_lazy('expense:category_list')

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        return super().get_context_data(**kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        user = get_object_or_404(User, username=self.request.user)
        categories = (
            user.category_expense_users.select_related('user')
            .order_by('parent_category__name', 'name')
            .all()
        )
        kwargs['user'] = self.request.user
        kwargs['depth'] = self.depth
        kwargs['category_queryset'] = categories
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
        messages.error(
            self.request,
            'Ошибка при добавлении категории. Проверьте введенные данные.',
        )
        return self.render_to_response(self.get_context_data(form=form))


class ExpenseCategoryDeleteView(
    ExpenseCategoryBaseView,
    DeleteObjectMixin,
):
    success_message = constants.SUCCESS_CATEGORY_EXPENSE_DELETED
    error_message = constants.ACCESS_DENIED_DELETE_EXPENSE_CATEGORY

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class ExpenseGroupAjaxView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        group_id = request.GET.get('group_id')
        user = request.user
        expenses = Expense.objects.none()
        receipt_expense_list = []
        if not group_id or group_id == 'my':
            expenses = Expense.objects.filter(user=user)
            group_users = [user]
        else:
            if user.groups.filter(id=group_id).exists():
                group_users = list(User.objects.filter(groups__id=group_id))
                expenses = Expense.objects.filter(user__in=group_users)
            else:
                group_users = []
        expenses = expenses.select_related('user', 'category', 'account').order_by(
            '-date',
        )
        if group_users:
            receipt_expenses = (
                Receipt.objects.filter(user__in=group_users, operation_type=1)
                .annotate(
                    month=TruncMonth('receipt_date'),
                    year=ExtractYear('receipt_date'),
                )
                .values('month', 'year', 'account__id', 'account__name_account', 'user')
                .annotate(amount=Sum('total_sum'))
                .order_by('-year', '-month')
            )
            for receipt in receipt_expenses:
                month_date = receipt['month']
                date_label = month_date.strftime('%B %Y') if month_date else ''
                receipt_user = User.objects.get(id=receipt['user'])
                receipt_expense_list.append(
                    {
                        'id': f'receipt_{receipt["year"]}{month_date.strftime("%m")}_{receipt["account__name_account"]}_{receipt["user"]}',
                        'date': month_date,
                        'date_label': date_label,
                        'amount': receipt['amount'],
                        'category': {
                            'name': 'Покупки по чекам',
                            'parent_category': None,
                        },
                        'account': {'name_account': receipt['account__name_account']},
                        'user': receipt_user,  # всегда объект User
                        'is_receipt': True,
                    },
                )

        all_expenses = list(expenses) + receipt_expense_list
        context = {'expenses': all_expenses, 'request': request}
        html = render_to_string(
            'expense/_expense_table_block.html',
            context,
            request=request,
        )
        return HttpResponse(html)


class ExpenseDataAjaxView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        group_id = request.GET.get('group_id')
        user = request.user
        expenses = Expense.objects.none()
        receipt_expense_list = []

        if group_id == 'my' or not group_id:
            expenses = Expense.objects.filter(user=user)
            group_users = [user]
        else:
            try:
                group = Group.objects.get(pk=group_id)
                group_users = list(group.user_set.all())
                expenses = Expense.objects.filter(user__in=group_users)
            except Group.DoesNotExist:
                group_users = []
                expenses = Expense.objects.none()

        if group_users:
            receipts = Receipt.objects.filter(
                user__in=group_users,
                operation_type=1,
            ).select_related('account', 'user')
            for receipt in receipts:
                print(receipt.total_sum, 'receipt')
                receipt_expense_list.append(
                    {
                        'id': f'receipt_{receipt.pk}',
                        'date': receipt.receipt_date.strftime('%d.%m.%Y')
                        if receipt.receipt_date
                        else '',
                        'amount': float(receipt.total_sum)
                        if receipt.total_sum is not None
                        else 0,
                        'category_name': 'Покупки по чекам',
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
                        'actions': '',  # Нет кнопок для чеков
                    },
                )

        data = []
        for expense in expenses.select_related('category', 'account', 'user').all():
            data.append(
                {
                    'id': expense.pk,
                    'date': expense.date.strftime('%d.%m.%Y'),
                    'amount': float(expense.amount)
                    if expense.amount is not None
                    else 0,
                    'category_name': expense.category.name if expense.category else '',
                    'account_name': expense.account.name_account
                    if expense.account
                    else '',
                    'user_name': expense.user.get_full_name() or expense.user.username
                    if expense.user
                    else '',
                    'user_id': expense.user.pk if expense.user else None,
                    'is_receipt': False,
                    'receipt_id': None,
                    'actions': '',  # Будет формироваться на фронте
                },
            )

        # Склеиваем обычные расходы и чеки
        all_data = data + receipt_expense_list
        return JsonResponse({'data': all_data})
