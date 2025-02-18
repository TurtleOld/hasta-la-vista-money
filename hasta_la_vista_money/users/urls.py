from django.urls import path
from hasta_la_vista_money.authentication.apis import ListUsersAPIView, LoginUserAPIView
from hasta_la_vista_money.users.views import (
    CreateUser,
    ListUsers,
    UpdateUserView,
)

app_name = 'users'
urlpatterns = [
    path('registration/', CreateUser.as_view(), name='registration'),
    path('profile/<int:pk>/', ListUsers.as_view(), name='profile'),
    path('login/', LoginUserAPIView.as_view(), name='login'),
    path('update_user/<int:pk>', UpdateUserView.as_view(), name='update_user'),
    path(
        'list/user',
        ListUsersAPIView.as_view(),
        name='list_user',
    ),
]
