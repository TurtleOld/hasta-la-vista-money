"""Group-related URL configuration for users app."""

from django.urls import path

from hasta_la_vista_money.users.views import (
    AddUserToGroupView,
    DeleteUserFromGroupView,
    GroupCreateView,
    GroupDeleteView,
)

app_name = 'groups'

urlpatterns = [
    path('create/', GroupCreateView.as_view(), name='create'),
    path('delete/', GroupDeleteView.as_view(), name='delete'),
    path('add-user/', AddUserToGroupView.as_view(), name='add_user'),
    path('delete-user/', DeleteUserFromGroupView.as_view(), name='delete_user'),
]
