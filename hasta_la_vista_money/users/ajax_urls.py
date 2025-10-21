"""AJAX-related URL configuration for users app."""

from django.urls import path

from hasta_la_vista_money.users.views import (
    groups_for_user_ajax,
    groups_not_for_user_ajax,
)

app_name = 'ajax'

urlpatterns = [
    path('groups-for-user/', groups_for_user_ajax, name='groups_for_user'),
    path(
        'groups-not-for-user/',
        groups_not_for_user_ajax,
        name='groups_not_for_user',
    ),
]
