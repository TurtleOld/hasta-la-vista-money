"""API URL configuration for users app."""

from django.urls import path

from hasta_la_vista_money.users.apis import (
    AvailableGroupsAPIView,
    UserGroupsAPIView,
)

app_name = 'api'

urlpatterns = [
    path('groups/', UserGroupsAPIView.as_view(), name='groups'),
    path(
        'available-groups/',
        AvailableGroupsAPIView.as_view(),
        name='available_groups',
    ),
]

