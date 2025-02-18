from django.urls import path

from hasta_la_vista_money.authentication.apis import LoginUserAPIView

app_name = 'authentication'
urlpatterns = [path('login/', LoginUserAPIView.as_view(), name='login')]
