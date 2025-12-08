"""API URL configuration for income app."""

from django.urls import path

from hasta_la_vista_money.income.apis import (
    IncomeByGroupAPIView,
    IncomeDataAPIView,
    IncomeRetrieveAPIView,
)

app_name = 'api'

urlpatterns = [
    path('by-group/', IncomeByGroupAPIView.as_view(), name='by_group'),
    path('data/', IncomeDataAPIView.as_view(), name='data'),
    path('<int:pk>/', IncomeRetrieveAPIView.as_view(), name='retrieve'),
]

