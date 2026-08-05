from django.urls import path

from hasta_la_vista_money.deposits.views import (
    DepositAddRatePeriodView,
    DepositCapitalizeInterestView,
    DepositCloseView,
    DepositCreateView,
    DepositDetailView,
    DepositListView,
    DepositRecalculateForecastView,
    DepositRenewView,
    DepositTopUpView,
    DepositWithdrawView,
)

app_name = 'deposits'

urlpatterns = [
    path('', DepositListView.as_view(), name='list'),
    path('create/', DepositCreateView.as_view(), name='create'),
    path('<int:pk>/', DepositDetailView.as_view(), name='detail'),
    path('<int:pk>/withdraw/', DepositWithdrawView.as_view(), name='withdraw'),
    path('<int:pk>/top-up/', DepositTopUpView.as_view(), name='top-up'),
    path('<int:pk>/close/', DepositCloseView.as_view(), name='close'),
    path('<int:pk>/renew/', DepositRenewView.as_view(), name='renew'),
    path(
        '<int:pk>/capitalize/',
        DepositCapitalizeInterestView.as_view(),
        name='capitalize',
    ),
    path(
        '<int:pk>/terms/<int:term_id>/rate-periods/add/',
        DepositAddRatePeriodView.as_view(),
        name='add-rate-period',
    ),
    path(
        '<int:pk>/terms/<int:term_id>/forecast/recalculate/',
        DepositRecalculateForecastView.as_view(),
        name='recalculate-forecast',
    ),
]
