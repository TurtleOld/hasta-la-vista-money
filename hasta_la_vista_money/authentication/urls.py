from django.urls import path

from hasta_la_vista_money.authentication.views import (
    CookieTokenObtainPairView,
    CookieTokenRefreshView,
    SessionTokenObtainView,
)

app_name = 'authentication'
urlpatterns = [
    path('token/', CookieTokenObtainPairView.as_view(), name='token'),
    path(
        'token/refresh/',
        CookieTokenRefreshView.as_view(),
        name='token_refresh',
    ),
    path(
        'token/session/',
        SessionTokenObtainView.as_view(),
        name='token_session',
    ),
]
