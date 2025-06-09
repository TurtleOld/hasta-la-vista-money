import json
from typing import Any, Optional

from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import ValidationError
from django.core.handlers.wsgi import WSGIRequest
from django.db.models import Sum
from django.http import HttpRequest, JsonResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView
from hasta_la_vista_money import constants
from hasta_la_vista_money.commonlogic.views import collect_info_receipt
from hasta_la_vista_money.custom_mixin import (
    CustomNoPermissionMixin,
    DeleteObjectMixin,
)
from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.finance_account.forms import (
    AddAccountForm,
    TransferMoneyAccountForm,
)
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.finance_account.prepare import (
    collect_info_expense,
    collect_info_income,
    sort_expense_income,
)
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.users.models import User


class BaseView:
    template_name = 'finance_account/account.html'
    success_url = reverse_lazy('finance_account:list')


class AccountBaseView(BaseView):
    model = Account


class AccountView(
    CustomNoPermissionMixin,
    SuccessMessageMixin,
    AccountBaseView,
    ListView,
):
    """
    Представление отображающее список счетов и финансовую аналитику.

    Attributes:
        context_object_name (str): Имя переменной контекста, передаваемой в шаблон.
        no_permission_url (str): URL для перенаправления пользователя, если у него нет доступа.
    """

    context_object_name = 'finance_account'
    no_permission_url = reverse_lazy('login')

    @classmethod
    def collect_datasets(cls, request: HttpRequest) -> tuple:
        """
        Собирает данные о расходах и доходах пользователя.

        Parameters:
            request (HttpRequest): HTTP-запрос с информацией о пользователе.

        Returns:
            Два набора данных с расходами и доходами, отсортированные по дате.
        """
        expense_dataset = (
            Expense.objects.filter(
                user=request.user,
            )
            .values(
                'date',
            )
            .annotate(
                total_amount=Sum('amount'),
            )
            .order_by('date')
        )

        income_dataset = (
            Income.objects.filter(
                user=request.user,
            )
            .values(
                'date',
            )
            .annotate(
                total_amount=Sum('amount'),
            )
            .order_by('date')
        )

        return expense_dataset, income_dataset

    @classmethod
    def transform_data(cls, dataset) -> tuple:
        """
        Преобразует набор данных в списки дат и сумм.

        Parameters:
            dataset (QuerySet): Набор данных с датами и суммами.

        Returns:
            Два списка — один с отформатированными датами, другой с суммами.
        """
        dates = []
        amounts = []

        for date_amount in dataset:
            dates.append(
                date_amount['date'].strftime('%Y-%m-%d'),
            )
            amounts.append(float(date_amount['total_amount']))

        return dates, amounts

    @classmethod
    def transform_data_expense(cls, expense_dataset):
        """Преобразует набор данных о расходах в списки дат и сумм."""
        return cls.transform_data(expense_dataset)

    @classmethod
    def transform_data_income(cls, income_dataset):
        """Преобразует набор данных о доходах в списки дат и сумм."""
        return cls.transform_data(income_dataset)

    @classmethod
    def unique_data(cls, dates, amounts):
        """Объединяет дублирующиеся даты и суммы в уникальные списки."""
        unique_dates = []
        unique_amounts = []

        for data_index, date in enumerate(dates):
            if date not in unique_dates:
                unique_dates.append(date)
                unique_amounts.append(amounts[data_index])
            else:
                index = unique_dates.index(date)
                unique_amounts[index] += amounts[index]

        return unique_dates, unique_amounts

    @classmethod
    def unique_expense_data(cls, expense_dates, expense_amounts):
        """Возвращает уникальные даты и суммы для расходов."""
        return cls.unique_data(expense_dates, expense_amounts)

    @classmethod
    def unique_income_data(cls, income_dates, income_amounts):
        """Возвращает уникальные даты и суммы для доходов."""
        return cls.unique_data(income_dates, income_amounts)

    def get_context_data(self, **kwargs) -> dict[str, Any] | None:
        """
        Собирает контекст данных для отображения на странице, включая счета,
        аналитические данные по доходам и расходам,
        формы для добавления счетов и перевода средств,
        а также журнал переводов.

        Parameters:
            kwargs (dict): Дополнительные параметры контекста.

        Returns:
            Контекст данных для отображения на странице.
        """
        expense_dataset, income_dataset = self.collect_datasets(self.request)

        expense_dates, expense_amounts = self.transform_data_expense(
            expense_dataset,
        )
        income_dates, income_amounts = self.transform_data_income(
            income_dataset,
        )

        unique_expense_dates, unique_expense_amounts = self.unique_expense_data(
            expense_dates,
            expense_amounts,
        )

        unique_income_dates, unique_income_amounts = self.unique_income_data(
            income_dates,
            income_amounts,
        )

        # Combine unique dates for both expense and income to create a single time axis
        all_dates = sorted(set(unique_expense_dates + unique_income_dates))

        # Create data points for expense and income that match the combined dates
        expense_series_data = [
            (
                unique_expense_amounts[unique_expense_dates.index(date)]
                if date in unique_expense_dates
                else 0
            )
            for date in all_dates
        ]

        income_series_data = [
            (
                unique_income_amounts[unique_income_dates.index(date)]
                if date in unique_income_dates
                else 0
            )
            for date in all_dates
        ]

        # Create a combined chart with both expense and income data
        chart_combined = {
            'chart': {
                'type': 'line',
                'borderColor': '#000000',
                'borderWidth': 1,
                'height': 300,
            },
            'title': {'text': _('Аналитика')},
            'xAxis': [
                {
                    'categories': all_dates,
                    'title': {'text': _('Дата')},
                },
            ],
            'yAxis': {'title': {'text': _('Сумма')}},
            'series': [
                {
                    'name': _('Расходы'),
                    'data': expense_series_data,
                    'color': 'red',
                },
                {
                    'name': _('Доходы'),
                    'data': income_series_data,
                    'color': 'green',
                },
            ],
            'credits': {
                'enabled': False,
            },
            'exporting': {
                'enabled': False,
            },
            'responsive': {
                'rules': [
                    {
                        'condition': {'maxWidth': 700},
                        'chartOptions': {
                            'legend': {
                                'layout': 'horizontal',
                                'align': 'center',
                                'verticalAlign': 'bottom',
                            },
                        },
                    },
                ],
            },
        }

        if self.request.user.is_authenticated:
            user = get_object_or_404(
                User,
                username=self.request.user,
            )

            accounts = user.finance_account_users.select_related('user').all()

            sum_all_accounts = user.finance_account_users.aggregate(
                Sum('balance'),
            )['balance__sum']

            receipt_info_by_month = collect_info_receipt(user=user)

            income = collect_info_income(user)
            expenses = collect_info_expense(user)
            income_expense = sort_expense_income(expenses, income)

            account_transfer_money = user.finance_account_users.select_related(
                'user',
            ).all()
            initial_form_data = {
                'from_account': account_transfer_money.first(),
                'to_account': account_transfer_money.first(),
            }

            transfer_money_log = user.transfer_money.select_related(
                'to_account',
                'from_account',
            ).all()

            context = super().get_context_data(**kwargs)
            context['accounts'] = accounts
            context['add_account_form'] = AddAccountForm()
            context['transfer_money_form'] = TransferMoneyAccountForm(
                user=self.request.user,
                initial=initial_form_data,
            )
            context['receipt_info_by_month'] = receipt_info_by_month
            context['income_expense'] = income_expense
            context['transfer_money_log'] = transfer_money_log
            context['chart_combine'] = json.dumps(chart_combined)
            context['sum_all_accounts'] = sum_all_accounts

            return context


class AccountCreateView(CreateView):
    """
    Представление для создания нового счёта.

    Это представление использует форму для создания нового счета, проверяет её
    на валидность и сохраняет данные в случае успеха. Возвращает JSON-ответ с
    результатом операции.

    Attributes:
        form_class (AddAccountForm): Форма для создания нового счета.
        no_permission_url (str): URL, на который перенаправляется пользователь, если у него нет прав.
    """

    form_class = AddAccountForm
    template_name = 'finance_account/add_account.html'
    model = Account
    no_permission_url = reverse_lazy('login')
    success_message = constants.SUCCESS_MESSAGE_ADDED_ACCOUNT

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['add_account_form'] = AddAccountForm()
        return context

    def get_success_url(self):
        return reverse_lazy('applications:list')

    def form_valid(self, form):
        account = form.save(commit=False)
        account.user = self.request.user
        account.save()
        messages.success(self.request, self.success_message)
        return HttpResponseRedirect(self.get_success_url())


class ChangeAccountView(
    CustomNoPermissionMixin,
    SuccessMessageMixin,
    AccountBaseView,
    UpdateView,
):
    """
    Представление для изменения существующего счета.

    Это представление позволяет пользователю редактировать данные уже созданного
    счета. После успешного редактирования выводится сообщение об успешной операции.

    Attributes:
        form_class (AddAccountForm): Форма для редактирования счета.
        template_name (str): Имя шаблона, используемого для отображения страницы редактирования счета.
        success_message (str): Сообщение, которое отображается после успешного обновления счета.
    """

    form_class = AddAccountForm
    template_name = 'finance_account/change_account.html'
    success_message = constants.SUCCESS_MESSAGE_CHANGED_ACCOUNT

    def get_context_data(self, **kwargs) -> dict:
        """
        Добавляет дополнительные данные в контекст шаблона.
        Включает форму для редактирования счета в контекст.

        Returns:
            Контекст с добавленной формой редактирования счета.
        """
        context = super().get_context_data(**kwargs)
        form_class = self.get_form_class()
        form = form_class(**self.get_form_kwargs())
        context['add_account_form'] = form
        return context


class TransferMoneyAccountView(
    CustomNoPermissionMixin,
    SuccessMessageMixin,
    AccountBaseView,
    View,
):
    """
    Представление для перевода средств между счетами.
    """

    form_class = TransferMoneyAccountForm
    success_message = constants.SUCCESS_MESSAGE_TRANSFER_MONEY

    def post(self, request: WSGIRequest, *args, **kwargs) -> JsonResponse:
        form = self.form_class(user=request.user, data=request.POST)

        if (
            form.is_valid()
            and request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'
        ):
            try:
                form.save()
                messages.success(request, self.success_message)
                return JsonResponse({'success': True})
            except ValidationError as e:
                return JsonResponse({'success': False, 'errors': str(e)})
        else:
            return JsonResponse({'success': False, 'errors': form.errors})


class DeleteAccountView(DeleteObjectMixin):
    """
    Представление для удаления счета.

    Это представление обрабатывает удаление счета и возвращает соответствующее
    сообщение об успехе или неудаче операции.

    Attributes:
        success_message (str): Сообщение, отображаемое при успешном удалении счета.
        error_message (str): Сообщение, отображаемое при неудаче удаления счета.
    """

    model = Account
    template_name = 'finance_account/finance_account.html'
    success_url = reverse_lazy('finance_account:list')
    success_message = constants.SUCCESS_MESSAGE_DELETE_ACCOUNT[:]
    error_message = constants.UNSUCCESSFULLY_MESSAGE_DELETE_ACCOUNT[:]
