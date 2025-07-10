"""User app URL configuration."""

from django.urls import path, include
from hasta_la_vista_money.users.views import (
    CreateUser,
    ListUsers,
    LoginUser,
    SetPasswordUserView,
    UpdateUserView,
    UserStatisticsView,
    ExportUserDataView,
    SwitchThemeView,
)

app_name = 'users'

urlpatterns = [
    path('registration/', CreateUser.as_view(), name='registration'),
    path('profile/<int:pk>/', ListUsers.as_view(), name='profile'),
    path('profile/password/', SetPasswordUserView.as_view(), name='password'),
    path('login/', LoginUser.as_view(), name='login'),
    path('update-user/<int:pk>/', UpdateUserView.as_view(), name='update_user'),
    path('list/users/', ListUsers.as_view(), name='list_users'),
    path('statistics/', UserStatisticsView.as_view(), name='statistics'),
    path('export-data/', ExportUserDataView.as_view(), name='export_data'),
    path('set-theme/', SwitchThemeView.as_view(), name='set_theme'),
    path('groups/', include('hasta_la_vista_money.users.groups_urls')),
    path('ajax/', include('hasta_la_vista_money.users.ajax_urls')),
]
