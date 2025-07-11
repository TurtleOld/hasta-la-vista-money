from typing import Any, Dict

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import ValidationError
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponseRedirect, JsonResponse, HttpResponse
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView
from hasta_la_vista_money import constants
from hasta_la_vista_money.custom_mixin import DeleteObjectMixin
from hasta_la_vista_money.finance_account.mixins import GroupAccountMixin
from hasta_la_vista_money.finance_account.forms import (
    AddAccountForm,
    TransferMoneyAccountForm,
)
from hasta_la_vista_money.finance_account.models import Account, TransferMoneyLog
from django.template.loader import render_to_string

from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.finance_account import services as account_services
from asgiref.sync import sync_to_async
import structlog
from django.utils.translation import gettext_lazy as _

logger = structlog.get_logger(__name__)


class BaseView:
    template_name = 'finance_account/account.html'
    success_url = reverse_lazy('finance_account:list')


class AccountBaseView(BaseView):
    model = Account


class AccountView(
    LoginRequiredMixin,
    GroupAccountMixin,
    SuccessMessageMixin,
    AccountBaseView,
    ListView,
):
    """
    Displays a list of user or group accounts with related forms and statistics.

    Shows all accounts for the current user or selected group, provides forms for adding and transferring accounts,
    and displays recent transfer logs and account balances.
    """

    context_object_name = 'finance_account'

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        """
        Build the context for the account list page, including accounts, forms, logs, and statistics.

        Args:
            **kwargs: Additional context parameters.

        Returns:
            dict: Context for rendering the account list template.
        """
        try:
            context = super().get_context_data(**kwargs)
            context.update(self._get_accounts_context())
            context.update(self._get_forms_context())
            context.update(self._get_transfer_log_context())
            context.update(self._get_sums_context())
            return context
        except Exception:
            logger.error(
                'Ошибка при формировании контекста счетов',
                exc_info=True,
                user_id=getattr(self.request.user, 'id', None),
            )
            from django.contrib import messages

            messages.error(
                self.request,
                _(
                    'Произошла ошибка при загрузке счетов. Пожалуйста, попробуйте позже.'
                ),
            )
            return super().get_context_data(**kwargs)

    def _get_accounts_context(self) -> Dict[str, Any]:
        """
        Get context with accounts and user groups.

        Returns:
            dict: Accounts and user groups for the current user.
        """
        user = self.request.user
        accounts = self.get_accounts(user)
        return {
            'accounts': accounts,
            'user_groups': user.groups.all(),
        }

    def _get_forms_context(self) -> Dict[str, Any]:
        """
        Get context with forms for adding and transferring accounts.

        Returns:
            dict: Forms for account creation and money transfer.
        """
        user = self.request.user
        account_transfer_money = (
            Account.objects.by_user(user).select_related('user').all()
        )
        initial_form_data = {
            'from_account': account_transfer_money.first(),
            'to_account': account_transfer_money.first(),
        }
        return {
            'add_account_form': AddAccountForm(),
            'transfer_money_form': TransferMoneyAccountForm(
                user=user,
                initial=initial_form_data,
            ),
        }

    def _get_transfer_log_context(self) -> Dict[str, Any]:
        """
        Get context with recent transfer logs.

        Returns:
            dict: Recent transfer logs for the current user.
        """
        user = self.request.user
        transfer_money_log = TransferMoneyLog.objects.by_user(user)
        return {
            'transfer_money_log': transfer_money_log,
        }

    def _get_sums_context(self) -> Dict[str, Any]:
        """
        Get context with account balance statistics.

        Returns:
            dict: Total balances for user and group accounts.
        """
        user = self.request.user
        accounts = Account.objects.by_user(user)
        sum_all_accounts = account_services.get_sum_all_accounts(accounts)
        user_groups = user.groups.all()
        if user_groups.exists():
            users_in_groups = User.objects.filter(groups__in=user_groups).distinct()
            sum_all_accounts_in_group = account_services.get_sum_all_accounts(
                Account.objects.filter(user__in=users_in_groups).select_related('user')
            )
        else:
            sum_all_accounts_in_group = account_services.get_sum_all_accounts(
                Account.objects.by_user(user).select_related('user')
            )
        return {
            'sum_all_accounts': sum_all_accounts,
            'sum_all_accounts_in_group': sum_all_accounts_in_group,
        }


class AccountCreateView(LoginRequiredMixin, CreateView):
    """
    Handles creation of a new account for the current user.

    Presents a form for account creation, validates and saves the account, and provides user feedback.
    """

    form_class = AddAccountForm
    template_name = 'finance_account/add_account.html'
    model = Account
    no_permission_url = reverse_lazy('login')
    success_message = constants.SUCCESS_MESSAGE_ADDED_ACCOUNT

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        """
        Add the account creation form to the context.

        Args:
            **kwargs: Additional context parameters.

        Returns:
            dict: Context with the account creation form.
        """
        context = super().get_context_data(**kwargs)
        context['add_account_form'] = AddAccountForm()
        return context

    def get_success_url(self) -> str:
        """
        Get the URL to redirect to after successful account creation.

        Returns:
            str: Success redirect URL.
        """
        return reverse_lazy('applications:list')

    def form_valid(self, form: AddAccountForm) -> HttpResponseRedirect:
        """
        Save the new account and handle success or error feedback.

        Args:
            form (AddAccountForm): The validated account creation form.

        Returns:
            HttpResponseRedirect: Redirect response after processing the form.
        """
        try:
            account = form.save(commit=False)
            account.user = self.request.user
            account.save()
            messages.success(self.request, self.success_message)
            return HttpResponseRedirect(self.get_success_url())
        except Exception:
            logger.error(
                'Ошибка при создании счета',
                exc_info=True,
                user_id=getattr(self.request.user, 'id', None),
            )
            messages.error(
                self.request,
                _('Не удалось создать счет. Пожалуйста, попробуйте позже.'),
            )
            return HttpResponseRedirect(self.get_success_url())


class ChangeAccountView(
    LoginRequiredMixin,
    SuccessMessageMixin,
    AccountBaseView,
    UpdateView,
):
    """
    Handles editing of an existing account.

    Presents a form for editing account details and provides user feedback on success or error.
    """

    form_class = AddAccountForm
    template_name = 'finance_account/change_account.html'
    success_message = constants.SUCCESS_MESSAGE_CHANGED_ACCOUNT

    def get_context_data(self, **kwargs: Any) -> dict:
        """
        Add the account edit form to the context.

        Args:
            **kwargs: Additional context parameters.

        Returns:
            dict: Context with the account edit form.
        """
        try:
            context = super().get_context_data(**kwargs)
            form_class = self.get_form_class()
            form = form_class(**self.get_form_kwargs())
            context['add_account_form'] = form
            return context
        except Exception:
            logger.error(
                'Ошибка при формировании контекста изменения счета',
                exc_info=True,
                user_id=getattr(self.request.user, 'id', None),
            )
            from django.contrib import messages

            messages.error(
                self.request,
                _(
                    'Произошла ошибка при загрузке формы изменения счета. Пожалуйста, попробуйте позже.'
                ),
            )
            return super().get_context_data(**kwargs)


class TransferMoneyAccountView(
    LoginRequiredMixin,
    SuccessMessageMixin,
    AccountBaseView,
    View,
):
    """
    Handles money transfers between user accounts.

    Validates and processes money transfer requests, providing user feedback and error handling.
    """

    form_class = TransferMoneyAccountForm
    success_message = constants.SUCCESS_MESSAGE_TRANSFER_MONEY

    def post(self, request: WSGIRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        """
        Process a POST request to transfer money between accounts.

        Args:
            request (WSGIRequest): The HTTP request object.

        Returns:
            JsonResponse: JSON response indicating success or error.
        """
        try:
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
        except Exception:
            logger.error(
                'Ошибка при переводе средств между счетами',
                exc_info=True,
                user_id=getattr(request.user, 'id', None),
            )
            return JsonResponse(
                {
                    'success': False,
                    'errors': str(
                        _(
                            'Произошла ошибка при переводе средств. Пожалуйста, попробуйте позже.'
                        )
                    ),
                },
                status=500,
            )


class DeleteAccountView(LoginRequiredMixin, DeleteObjectMixin):
    """
    Handles deletion of an account.

    Deletes the specified account and provides user feedback on success or failure.
    """

    model = Account
    template_name = 'finance_account/finance_account.html'
    success_url = reverse_lazy('finance_account:list')
    success_message = constants.SUCCESS_MESSAGE_DELETE_ACCOUNT[:]
    error_message = constants.UNSUCCESSFULLY_MESSAGE_DELETE_ACCOUNT[:]


class AjaxAccountsByGroupView(View):
    """
    Returns rendered HTML for accounts filtered by group via AJAX.

    Handles asynchronous requests for account cards, with error logging and user-friendly error messages.
    """

    async def get(
        self, request: WSGIRequest, *args: Any, **kwargs: Any
    ) -> HttpResponse:
        """
        Handle GET request for accounts by group via AJAX.

        Args:
            request (WSGIRequest): The HTTP request object.

        Returns:
            HttpResponse: Rendered HTML or JSON error response.
        """
        group_id = request.GET.get('group_id')
        user = request.user
        try:
            accounts = await sync_to_async(
                account_services.get_accounts_for_user_or_group
            )(user, group_id)
            html = await sync_to_async(render_to_string)(
                'finance_account/_account_cards_block.html',
                {'accounts': accounts, 'request': request},
            )
            return HttpResponse(html)
        except Exception:
            logger.error(
                'Ошибка при получении счетов по группе',
                exc_info=True,
                group_id=group_id,
                user_id=getattr(user, 'id', None),
            )
            return JsonResponse(
                {
                    'success': False,
                    'error': str(
                        _(
                            'Произошла ошибка при получении счетов. Пожалуйста, попробуйте позже.'
                        )
                    ),
                },
                status=500,
            )
