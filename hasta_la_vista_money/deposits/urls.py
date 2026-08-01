from django.urls import path

from hasta_la_vista_money.deposits.views import (
    DepositAddRatePeriodView,
    DepositCreateView,
    DepositDetailView,
    DepositListView,
)

app_name = 'deposits'

urlpatterns = [
    path('', DepositListView.as_view(), name='list'),
    path('create/', DepositCreateView.as_view(), name='create'),
    path('<int:pk>/', DepositDetailView.as_view(), name='detail'),
    path(
        '<int:pk>/terms/<int:term_id>/rate-periods/add/',
        DepositAddRatePeriodView.as_view(),
        name='add-rate-period',
    ),
]
