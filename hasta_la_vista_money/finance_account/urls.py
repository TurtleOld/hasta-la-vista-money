"""URL configuration for finance account management.

This module defines the URL patterns for finance account operations including
account listing, creation, editing, deletion, money transfers,
and API endpoints.
"""

from django.urls import path

from hasta_la_vista_money.finance_account.apis import AccountListCreateAPIView
from hasta_la_vista_money.finance_account.views import (
    AccountCreateView,
    AccountView,
    AjaxAccountsByGroupView,
    ChangeAccountView,
    DeleteAccountView,
    TransferMoneyAccountView,
)

app_name = 'finance_account'
urlpatterns = [
    path(
        '',
        AccountView.as_view(),
        name='list',
    ),
    path(
        'create/',
        AccountCreateView.as_view(),
        name='create',
    ),
    path(
        'change/<int:pk>/',
        ChangeAccountView.as_view(),
        name='change',
    ),
    path(
        'delete/<int:pk>',
        DeleteAccountView.as_view(),
        name='delete_account',
    ),
    path(
        'transfer-money/',
        TransferMoneyAccountView.as_view(),
        name='transfer_money',
    ),
    path(
        'list/',
        AccountListCreateAPIView.as_view(),
        name='api_list',
    ),
    path(
        'ajax/accounts_by_group/',
        AjaxAccountsByGroupView.as_view(),
        name='ajax_accounts_by_group',
    ),
]
