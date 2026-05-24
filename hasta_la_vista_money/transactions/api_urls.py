"""API URL configuration for the transactions app."""

from django.urls import path

from hasta_la_vista_money.transactions.apis import (
    TransactionByGroupAPIView,
    TransactionDataAPIView,
    TransactionRetrieveAPIView,
)

app_name = 'api'

urlpatterns = [
    path('by-group/', TransactionByGroupAPIView.as_view(), name='by_group'),
    path('data/', TransactionDataAPIView.as_view(), name='data'),
    path('<int:pk>/', TransactionRetrieveAPIView.as_view(), name='retrieve'),
]
