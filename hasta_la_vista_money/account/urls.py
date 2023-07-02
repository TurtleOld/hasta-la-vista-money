from django.urls import path
from hasta_la_vista_money.applications.views import (
    ChangeAccountView,
    DeleteAccountView,
)

app_name = 'account'
urlpatterns = [
    path(
        '<int:pk>',
        DeleteAccountView.as_view(),
        name='delete_account',

    ),
    path(
        '<int:pk>/change',
        ChangeAccountView.as_view(),
        name='change',
    ),
]
