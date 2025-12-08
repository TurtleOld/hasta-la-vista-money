"""API URL configuration for expense app."""

from django.urls import path

from hasta_la_vista_money.expense.apis import (
    ExpenseByGroupAPIView,
    ExpenseDataAPIView,
)

app_name = 'api'

urlpatterns = [
    path('by-group/', ExpenseByGroupAPIView.as_view(), name='by_group'),
    path('data/', ExpenseDataAPIView.as_view(), name='data'),
]

