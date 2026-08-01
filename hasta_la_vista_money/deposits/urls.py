from django.urls import path

from hasta_la_vista_money.deposits.views import (
    DepositCreateView,
    DepositDetailView,
    DepositListView,
)

app_name = 'deposits'

urlpatterns = [
    path('', DepositListView.as_view(), name='list'),
    path('create/', DepositCreateView.as_view(), name='create'),
    path('<int:pk>/', DepositDetailView.as_view(), name='detail'),
]
