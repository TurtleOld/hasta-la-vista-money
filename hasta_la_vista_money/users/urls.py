from django.urls import path
from hasta_la_vista_money.users.views import (
    AddUserToGroupView,
    CreateUser,
    DeleteUserFromGroupView,
    ExportUserDataView,
    GroupCreateView,
    GroupDeleteView,
    ListUsers,
    LoginUser,
    SetPasswordUserView,
    UpdateUserView,
    UserStatisticsView,
    groups_for_user_ajax,
    groups_not_for_user_ajax,
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
    path(
        "groups/delete_user/",
        DeleteUserFromGroupView.as_view(),
        name="del_user_to_group",
    ),
    path("ajax/groups_for_user/", groups_for_user_ajax, name="ajax_groups_for_user"),
    path(
        "ajax/groups_not_for_user/",
        groups_not_for_user_ajax,
        name="ajax_groups_not_for_user",
    ),
]
