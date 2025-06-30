from django.urls import path
from hasta_la_vista_money.users.views import (
    CreateUser,
    ExportUserDataView,
    ListUsers,
    LoginUser,
    SetPasswordUserView,
    UpdateUserView,
    UserStatisticsView,
    GroupCreateView,
    GroupDeleteView,
    AddUserToGroupView,
)

app_name = 'users'
urlpatterns = [
    path("registration/", CreateUser.as_view(), name="registration"),
    path("profile/<int:pk>/", ListUsers.as_view(), name="profile"),
    path(
        "profile/password/",
        SetPasswordUserView.as_view(),
        name="password",
    ),
    path("login/", LoginUser.as_view(), name="login"),
    path(
        "update_user/<int:pk>",
        UpdateUserView.as_view(),
        name="update_user",
    ),
    path("list/user", ListUsers.as_view(), name="list_user"),
    path("statistics/", UserStatisticsView.as_view(), name="statistics"),
    path("export_data/", ExportUserDataView.as_view(), name="export_data"),
    path("groups/create/", GroupCreateView.as_view(), name="group_create"),
    path("groups/delete/", GroupDeleteView.as_view(), name="group_delete"),
    path("groups/add_user/", AddUserToGroupView.as_view(), name="add_user_to_group"),
]
