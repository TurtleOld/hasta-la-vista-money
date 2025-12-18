from django.urls import path

from hasta_la_vista_money.budget.views import (
    ExpenseBudgetAPIView,
    IncomeBudgetAPIView,
)

app_name = 'api'

urlpatterns = [
    path(
        'expenses/',
        ExpenseBudgetAPIView.as_view(),
        name='expense_budget',
    ),
    path(
        'incomes/',
        IncomeBudgetAPIView.as_view(),
        name='income_budget',
    ),
]
