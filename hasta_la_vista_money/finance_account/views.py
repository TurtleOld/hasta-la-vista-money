"""Views for finance account management.

This module provides Django views for managing financial accounts including
listing, creation, editing, deletion, and money transfer operations. Includes
comprehensive error handling, user authentication, and AJAX support.
"""

from typing import TYPE_CHECKING, Any, cast

import structlog
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.http import HttpResponseRedirect
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import (
    CreateView,
    DeleteView,
    FormView,
    ListView,
    UpdateView,
)
from django_stubs_ext import StrOrPromise

from hasta_la_vista_money import constants

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import WSGIRequestWithContainer
from hasta_la_vista_money.custom_mixin import DeleteObjectMixin
from hasta_la_vista_money.finance_account.forms import (
    AddAccountForm,
    TransferMoneyAccountForm,
)
from hasta_la_vista_money.finance_account.mixins import GroupAccountMixin
from hasta_la_vista_money.finance_account.models import (
    Account,
)
from hasta_la_vista_money.users.models import User

logger = structlog.get_logger(__name__)


class BaseView:
    """Base view class with common template and success URL configuration."""

    def get_template_name(self) -> str:
        """Get the template name to render."""
        return 'finance_account/account.html'

    def get_success_url(self) -> str | StrOrPromise | None:
        """Get the URL to redirect to after successful operation."""
        return reverse_lazy('finance_account:list')


class AccountBaseView(BaseView):
    """Base view class for account-related operations."""

    def get_queryset(self) -> QuerySet[Account]:
        """Get the queryset of accounts for the current user."""
        request_obj = getattr(self, 'request', None)
        if request_obj is None:
            raise AttributeError('request attribute is required')
        request = cast('WSGIRequestWithContainer', request_obj)
        if not isinstance(request.user, User):
            msg = 'User must be authenticated'
            raise TypeError(msg)
        return Account.objects.by_user(request.user)


class AccountView(
    LoginRequiredMixin,
    GroupAccountMixin,
    SuccessMessageMixin[Any],
    ListView[Account],
    AccountBaseView,
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
    template_name = 'finance_account/account.html'

    def get_queryset(self) -> QuerySet[Account]:
        """Get the queryset of accounts for the current user or group.

        Uses GroupAccountMixin to get group_id and account_service
        to filter accounts by user or group.
        """
        request = cast('WSGIRequestWithContainer', self.request)
        account_service = request.container.core.account_service()
        group_id = self.get_group_id()
        return cast(
            'QuerySet[Account, Account]',
            account_service.get_accounts_for_user_or_group(
                request.user,
                group_id,
            ),
        )

    def get_context_data(
        self,
        *,
        object_list: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Build the context for the account list page.

        Delegates context building to AccountPageContextService.

        Args:
            **kwargs: Additional context parameters.

        Returns:
            dict: Context for rendering the account list template.
        """
        context = super().get_context_data(
            object_list=object_list,
            **kwargs,
        )

        request = cast('WSGIRequestWithContainer', self.request)
        container = request.container.finance_account
        page_context_service = container.account_page_context_service()

        user = page_context_service.get_user_with_groups(
            request.user.pk,
        )
        group_id = self.get_group_id()
        accounts = page_context_service.get_accounts_for_user_or_group(
            user,
            group_id,
        )

        # Get balance trend period from query parameters
        balance_trend_period = request.GET.get('balance_trend_period', '30d')

        page_context = page_context_service.build_account_list_context(
            user,
            accounts,
            group_id=group_id,
            balance_trend_period=balance_trend_period,
        )

        context.update(page_context)
        return context


class AccountCreateView(
    LoginRequiredMixin,
    CreateView[Account, AddAccountForm],
    AccountBaseView,
):
    """
    Handles creation of a new account for the current user.

    Presents a form for account creation, validates and saves the
    account, and provides user feedback.
    """

    form_class = AddAccountForm
    template_name = 'finance_account/add_account.html'
    no_permission_url = reverse_lazy('login')
    success_message = constants.SUCCESS_MESSAGE_ADDED_ACCOUNT

    def get_context_data(
        self,
        *,
        object_list: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Add the account creation form to the context.

        Args:
            **kwargs: Additional context parameters.

        Returns:
            dict: Context with the account creation form.
        """
        context = super().get_context_data(
            object_list=object_list,
            **kwargs,
        )
        context['add_account_form'] = AddAccountForm()
        return context

    def get_success_url(self) -> str:
        """
        Get the URL to redirect to after successful account creation.

        Returns:
            str: Success redirect URL.
        """
        return str(reverse_lazy('finance_account:list'))

    def form_valid(self, form: AddAccountForm) -> HttpResponseRedirect:
        """
        Save the new account and handle success or error feedback.

        Args:
            form (AddAccountForm): The validated account creation form.

        Returns:
            HttpResponseRedirect: Redirect response after processing the form.
        """
        request = cast('WSGIRequestWithContainer', self.request)
        try:
            account = form.save(commit=False)
            if not isinstance(request.user, User):
                raise TypeError('User must be authenticated')
            account.user = request.user
            account.save()
            messages.success(request, self.success_message)
            return HttpResponseRedirect(self.get_success_url())
        except Exception:
            logger.exception(
                'Ошибка при создании счета',
                user_id=getattr(request.user, 'id', None),
            )
            messages.error(
                request,
                _('Не удалось создать счет. Пожалуйста, попробуйте позже.'),
            )
            return HttpResponseRedirect(self.get_success_url())


class ChangeAccountView(
    LoginRequiredMixin,
    SuccessMessageMixin[AddAccountForm],
    UpdateView[Account, AddAccountForm],
    AccountBaseView,
):
    """
    Handles editing of an existing account.

    Presents a form for editing account details and provides user
    feedback on success or error.
    """

    model = Account
    form_class = AddAccountForm
    template_name = 'finance_account/change_account.html'
    success_message = constants.SUCCESS_MESSAGE_CHANGED_ACCOUNT

    def get_context_data(
        self,
        *,
        object_list: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Add the account edit form to the context.

        Args:
            **kwargs: Additional context parameters.

        Returns:
            dict: Context with the account edit form.
        """
        try:
            context = super().get_context_data(
                object_list=object_list,
                **kwargs,
            )
            form_class = self.get_form_class()
            form = form_class(**self.get_form_kwargs())
            context['add_account_form'] = form
        except Exception:
            request = cast('WSGIRequestWithContainer', self.request)
            logger.exception(
                'Ошибка при формировании контекста изменения счета',
                user_id=getattr(request.user, 'id', None),
            )
            messages.error(
                request,
                _(
                    'Произошла ошибка при загрузке формы изменения счета. '
                    'Пожалуйста, попробуйте позже.',
                ),
            )
            return super().get_context_data(
                object_list=object_list,
                **kwargs,
            )
        else:
            return context

    def form_valid(self, form: AddAccountForm) -> HttpResponseRedirect:
        request = cast('WSGIRequestWithContainer', self.request)
        try:
            account = form.save(commit=False)
            if not isinstance(request.user, User):
                raise TypeError('User must be authenticated')
            account.user = request.user
            account.save()
            messages.success(request, self.success_message)
            return HttpResponseRedirect(str(self.get_success_url()))
        except ValidationError as e:
            form.add_error(None, str(e))
            messages.error(request, str(e))
            return self.form_invalid(form)  # type: ignore[return-value]
        except Exception:
            logger.exception(
                'Ошибка при изменении счета',
                user_id=getattr(request.user, 'id', None),
            )
            form.add_error(
                None,
                _('Не удалось изменить счет. Пожалуйста, попробуйте позже.'),
            )
            messages.error(
                request,
                _('Не удалось изменить счет. Пожалуйста, попробуйте позже.'),
            )
            return self.form_invalid(form)  # type: ignore[return-value]

    def form_invalid(self, form: AddAccountForm) -> Any:
        context = self.get_context_data()
        context['add_account_form'] = form
        return self.render_to_response(context)


class TransferMoneyAccountView(
    LoginRequiredMixin,
    SuccessMessageMixin[TransferMoneyAccountForm],
    FormView[TransferMoneyAccountForm],
    AccountBaseView,
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
        request = cast('WSGIRequestWithContainer', self.request)
        kwargs = super().get_form_kwargs()
        kwargs['user'] = request.user
        kwargs['transfer_service'] = (
            request.container.finance_account.transfer_service()
        )
        kwargs['account_repository'] = (
            request.container.finance_account.account_repository()
        )
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
        request = cast('WSGIRequestWithContainer', self.request)
        try:
            cleaned_data = form.cleaned_data
            transfer_service = (
                request.container.finance_account.transfer_service()
            )
            transfer_service.transfer_money(
                from_account=cleaned_data['from_account'],
                to_account=cleaned_data['to_account'],
                amount=cleaned_data['amount'],
                user=cleaned_data['from_account'].user,
                exchange_date=cleaned_data.get('exchange_date'),
                notes=cleaned_data.get('notes'),
            )
            messages.success(request, self.success_message)
            return HttpResponseRedirect(reverse('finance_account:list'))
        except ValidationError as e:
            messages.error(request, str(e))
            return self.form_invalid(form)  # type: ignore[return-value]
        except Exception:
            logger.exception(
                'Ошибка при переводе средств между счетами',
                user_id=getattr(request.user, 'id', None),
            )
            messages.error(
                request,
                _(
                    'Произошла ошибка при переводе средств. '
                    'Пожалуйста, попробуйте позже.',
                ),
            )
            return self.form_invalid(form)  # type: ignore[return-value]


class DeleteAccountView(
    DeleteObjectMixin,
    LoginRequiredMixin,
    DeleteView[Account, Any],
):
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
