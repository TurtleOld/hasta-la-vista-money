"""AJAX-related URL configuration for users app."""

from django.urls import path

from hasta_la_vista_money.users.apis import (
    AvailableGroupsAPIView,
    UserGroupsAPIView,
)

app_name = 'ajax'

urlpatterns = [
    path(
        'groups-for-user/',
        UserGroupsAPIView.as_view(),
        name='groups_for_user',
    ),
    path(
        'groups-not-for-user/',
        AvailableGroupsAPIView.as_view(),
        name='groups_not_for_user',
    ),
]
