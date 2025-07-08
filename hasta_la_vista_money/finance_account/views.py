from typing import Any, Dict

from django.contrib import messages
from django.contrib.auth.models import Group
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import ValidationError
from django.core.handlers.wsgi import WSGIRequest
from django.db.models import Sum
from django.http import HttpResponseRedirect, JsonResponse, HttpResponse
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView
from hasta_la_vista_money import constants
from hasta_la_vista_money.custom_mixin import (
    CustomNoPermissionMixin,
    DeleteObjectMixin,
)
from hasta_la_vista_money.finance_account.forms import (
    AddAccountForm,
    TransferMoneyAccountForm,
)
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from django.template.loader import render_to_string

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
    Представление отображающее список счетов.

    Attributes:
        context_object_name (str): Имя переменной контекста, передаваемой в шаблон.
        no_permission_url (str): URL для перенаправления пользователя, если у него нет доступа.
    """

    context_object_name = 'finance_account'
    no_permission_url = reverse_lazy('login')

    def get_context_data(self, **kwargs) -> Dict[str, Any]:
        """
        Собирает контекст данных для отображения на странице счетов.

        Parameters:
            kwargs (dict): Дополнительные параметры контекста.

        Returns:
            Контекст данных для отображения на странице.
        """
        context = super().get_context_data(**kwargs)

        if not self.request.user.is_authenticated:
            return context

        user = self.request.user
        group_id = self.request.GET.get('group_id')
        if group_id and group_id != 'my':
            try:
                group = Group.objects.get(pk=group_id)
                users_in_group = group.user_set.all()
                accounts = Account.objects.filter(user__in=users_in_group)
            except Group.DoesNotExist:
                accounts = Account.objects.none()
        else:
            accounts = Account.objects.filter(user=user)

        account_transfer_money = (
            Account.objects.filter(user=user).select_related('user').all()
        )
        initial_form_data = {
            'from_account': account_transfer_money.first(),
            'to_account': account_transfer_money.first(),
        }

        # Журнал переводов
        transfer_money_log = (
            TransferMoneyLog.objects.filter(user=user)
            .select_related('to_account', 'from_account')
            .order_by('-created_at')[:10]
        )

        # Сумма всех счетов
        sum_all_accounts = accounts.aggregate(total=Sum('balance'))['total'] or 0

        # Сумма всех счетов в группе
        user_groups = user.groups.all()

        if user_groups.exists():
            users_in_groups = User.objects.filter(groups__in=user_groups).distinct()
            sum_all_accounts_in_group = (
                Account.objects.filter(user__in=users_in_groups).aggregate(
                    total=Sum('balance')
                )['total']
                or 0
            )
        else:
            sum_all_accounts_in_group = (
                Account.objects.filter(user=user).aggregate(total=Sum('balance'))[
                    'total'
                ]
                or 0
            )

        context.update(
            {
                'accounts': accounts,
                'add_account_form': AddAccountForm(),
                'transfer_money_form': TransferMoneyAccountForm(
                    user=self.request.user,
                    initial=initial_form_data,
                ),
                'transfer_money_log': transfer_money_log,
                'sum_all_accounts': sum_all_accounts,
                'user_groups': self.request.user.groups.all(),
                'sum_all_accounts_in_group': sum_all_accounts_in_group,
            },
        )

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


class AjaxAccountsByGroupView(View):
    def get(self, request, *args, **kwargs):
        group_id = request.GET.get('group_id')
        user = request.user
        accounts = Account.objects.none()
        if group_id == 'my' or not group_id:
            accounts = Account.objects.filter(user=user)
        else:
            try:
                group = Group.objects.get(pk=group_id)
                users_in_group = group.user_set.all()
                accounts = Account.objects.filter(user__in=users_in_group)
            except Group.DoesNotExist:
                accounts = Account.objects.none()
        html = render_to_string(
            'finance_account/_account_cards_block.html',
            {'accounts': accounts, 'request': request},
        )
        return HttpResponse(html)
