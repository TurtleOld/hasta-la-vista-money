"""Views for finance account management.

This module provides Django views for managing financial accounts including
listing, creation, editing, deletion, and money transfer operations. Includes
comprehensive error handling, user authentication, and AJAX support.
"""

from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import ValidationError
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import (
    CreateView,
    DeleteView,
    FormView,
    ListView,
    UpdateView,
)

from hasta_la_vista_money import constants
from hasta_la_vista_money.custom_mixin import DeleteObjectMixin
from hasta_la_vista_money.finance_account import services as account_services
from hasta_la_vista_money.finance_account.forms import (
    AddAccountForm,
    TransferMoneyAccountForm,
)
from hasta_la_vista_money.finance_account.mixins import GroupAccountMixin
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.users.models import User

logger = structlog.get_logger(__name__)


class BaseView:  # type: ignore[misc]
    """Base view class with common template and success URL configuration."""

    template_name = 'finance_account/account.html'  # type: ignore[misc]
    success_url = reverse_lazy('finance_account:list')  # type: ignore[misc]


class AccountBaseView(BaseView):  # type: ignore[misc]
    """Base view class for account-related operations."""

    model = Account  # type: ignore[misc]


class AccountView(  # type: ignore[misc]
    LoginRequiredMixin,
    GroupAccountMixin,
    SuccessMessageMixin,
    AccountBaseView,
    ListView,
):
    """Display a list of user or group accounts with related forms
    and statistics.

    Shows all accounts for the current user or selected group, provides
    forms for adding and transferring accounts,
    and displays recent transfer logs and account balances. Supports
    group-based filtering and comprehensive
    financial data presentation.
    """

    context_object_name = 'finance_account'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Build the context for the account list page, including
        accounts, forms, logs, and statistics.

        Aggregates data from multiple sources to provide a comprehensive
        view of the user's
        financial accounts and related operations.

        Args:
            **kwargs: Additional context parameters.

        Returns:
            dict: Context for rendering the account list template.
        """
        context = super().get_context_data(**kwargs)
        context.update(self._get_accounts_context())
        context.update(self._get_forms_context())
        context.update(self._get_transfer_log_context())
        context.update(self._get_sums_context())
        return context

    def _get_accounts_context(self) -> dict[str, Any]:
        """
        Get context with accounts and user groups.

        Returns:
            dict: Accounts and user groups for the current user.
        """
        user = self.request.user
        accounts = self.get_accounts(user)  # type: ignore[arg-type]
        return {
            'accounts': accounts,
            'user_groups': user.groups.all(),  # type: ignore[union-attr]
        }

    def _get_forms_context(self) -> dict[str, Any]:
        """
        Get context with forms for adding and transferring accounts.

        Returns:
            dict: Forms for account creation and money transfer.
        """
        user = self.request.user
        account_transfer_money = (
            Account.objects.by_user(user).select_related('user').all()  # type: ignore[arg-type]
        )
        initial_form_data = {
            'from_account': account_transfer_money.first(),
            'to_account': account_transfer_money.first(),
        }
        return {
            'add_account_form': AddAccountForm(),
            'transfer_money_form': TransferMoneyAccountForm(
                user=user,  # type: ignore[arg-type]
                initial=initial_form_data,
            ),
        }

    def _get_transfer_log_context(self) -> dict[str, Any]:
        """
        Get context with recent transfer logs.

        Returns:
            dict: Recent transfer logs for the current user.
        """
        user = self.request.user
        transfer_money_log = TransferMoneyLog.objects.by_user(user)  # type: ignore[arg-type]
        return {
            'transfer_money_log': transfer_money_log,
        }

    def _get_sums_context(self) -> dict[str, Any]:
        """
        Get context with account balance statistics.

        Returns:
            dict: Total balances for user and group accounts.
        """
        user = self.request.user
        accounts = Account.objects.by_user(user)  # type: ignore[arg-type]
        sum_all_accounts = account_services.get_sum_all_accounts(accounts)
        user_groups = user.groups.all()  # type: ignore[union-attr]
        if user_groups.exists():
            users_in_groups = User.objects.filter(
                groups__in=user_groups,
            ).distinct()
            sum_all_accounts_in_group = account_services.get_sum_all_accounts(
                Account.objects.filter(user__in=users_in_groups).select_related(
                    'user',
                ),
            )
        else:
            sum_all_accounts_in_group = account_services.get_sum_all_accounts(
                Account.objects.by_user(user).select_related('user'),  # type: ignore[arg-type]
            )
        return {
            'sum_all_accounts': sum_all_accounts,
            'sum_all_accounts_in_group': sum_all_accounts_in_group,
        }


class AccountCreateView(LoginRequiredMixin, CreateView):
    """
    Handles creation of a new account for the current user.

    Presents a form for account creation, validates and saves the
    account, and provides user feedback.
    """

    form_class = AddAccountForm
    template_name = 'finance_account/add_account.html'
    model = Account
    no_permission_url = reverse_lazy('login')
    success_message = constants.SUCCESS_MESSAGE_ADDED_ACCOUNT

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
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
        return str(reverse_lazy('applications:list'))

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
            logger.exception(
                'Ошибка при создании счета',
                user_id=getattr(self.request.user, 'id', None),
            )
            messages.error(
                self.request,
                _('Не удалось создать счет. Пожалуйста, попробуйте позже.'),
            )
            return HttpResponseRedirect(self.get_success_url())


class ChangeAccountView(  # type: ignore[misc]
    LoginRequiredMixin,
    SuccessMessageMixin,
    AccountBaseView,
    UpdateView,
):
    """
    Handles editing of an existing account.

    Presents a form for editing account details and provides user
    feedback on success or error.
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
        except Exception:
            logger.exception(
                'Ошибка при формировании контекста изменения счета',
                user_id=getattr(self.request.user, 'id', None),
            )
            messages.error(
                self.request,
                _(
                    'Произошла ошибка при загрузке формы изменения счета. '
                    'Пожалуйста, попробуйте позже.',
                ),
            )
            return super().get_context_data(**kwargs)
        else:
            return context


class TransferMoneyAccountView(  # type: ignore[misc]
    LoginRequiredMixin,
    SuccessMessageMixin,
    AccountBaseView,
    FormView,
):
    """
    Handles money transfers between user accounts.

    Validates and processes money transfer requests, providing user
    feedback and error handling.
    """

    form_class = TransferMoneyAccountForm
    success_message = constants.SUCCESS_MESSAGE_TRANSFER_MONEY
    template_name = 'finance_account/transfer_money.html'

    def get_form_kwargs(self) -> dict[str, Any]:
        """Get form kwargs including user for account filtering."""
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(
        self,
        form: TransferMoneyAccountForm,
    ) -> HttpResponseRedirect:
        """
        Process valid form submission.

        Args:
            form: Validated form instance.

        Returns:
            HttpResponseRedirect: Redirect to account list with success message.
        """
        try:
            form.save()
            messages.success(self.request, self.success_message)
            return HttpResponseRedirect(reverse('finance_account:list'))
        except ValidationError as e:
            messages.error(self.request, str(e))
            return self.form_invalid(form)  # type: ignore[return-value]
        except Exception:
            logger.exception(
                'Ошибка при переводе средств между счетами',
                user_id=getattr(self.request.user, 'id', None),
            )
            messages.error(
                self.request,
                _(
                    'Произошла ошибка при переводе средств. '
                    'Пожалуйста, попробуйте позже.',
                ),
            )
            return self.form_invalid(form)  # type: ignore[return-value]


class DeleteAccountView(DeleteObjectMixin, LoginRequiredMixin, DeleteView):
    """
    Handles deletion of an account.

    Deletes the specified account and provides user feedback on
    success or failure.
    """

    model = Account
    template_name = 'finance_account/finance_account.html'
    success_url = reverse_lazy('finance_account:list')
    success_message = constants.SUCCESS_MESSAGE_DELETE_ACCOUNT[:]
    error_message = constants.UNSUCCESSFULLY_MESSAGE_DELETE_ACCOUNT[:]


class AjaxAccountsByGroupView(View):
    """
    Returns rendered HTML for accounts filtered by group via AJAX.

    Handles asynchronous requests for account cards, with error
    logging and user-friendly error messages.
    """

    async def get(
        self,
        request: WSGIRequest,
        *args: Any,
        **kwargs: Any,
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
                account_services.get_accounts_for_user_or_group,
            )(user, group_id)  # type: ignore[arg-type]
            html = await sync_to_async(render_to_string)(
                'finance_account/_account_cards_block.html',
                {'accounts': accounts, 'request': request},
            )
            return HttpResponse(html)
        except Exception:
            logger.exception(
                'Ошибка при получении счетов по группе',
                group_id=group_id,
                user_id=getattr(user, 'id', None),
            )
            return JsonResponse(
                {
                    'success': False,
                    'error': str(
                        _(
                            'Произошла ошибка при получении счетов. '
                            'Пожалуйста, попробуйте позже.',
                        ),
                    ),
                },
                status=500,
            )
