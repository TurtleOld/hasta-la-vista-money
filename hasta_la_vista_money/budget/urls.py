from django.urls import path

from hasta_la_vista_money.budget.apis import (
    ChangePlanningAPIView,
    GenerateDatesAPIView,
    SavePlanningAPIView,
)
from hasta_la_vista_money.budget.views import (
    BudgetView,
    ExpenseBudgetAPIView,
    ExpenseTableView,
    IncomeBudgetAPIView,
    IncomeTableView,
)

app_name = 'budget'
urlpatterns = [
    path('', BudgetView.as_view(), name='list'),
    path('expenses/', ExpenseTableView.as_view(), name='expense_table'),
    path('incomes/', IncomeTableView.as_view(), name='income_table'),
    path(
        'generate-date/',
        GenerateDatesAPIView.as_view(),
        name='generate_date',
    ),
    path(
        'change-planning/',
        ChangePlanningAPIView.as_view(),
        name='change_planning',
    ),
    path(
        'save-planning/',
        SavePlanningAPIView.as_view(),
        name='save_planning',
    ),
    path(
        'expenses/',
        ExpenseBudgetAPIView.as_view(),
        name='api_expense_budget',
    ),
    path(
        'incomes/',
        IncomeBudgetAPIView.as_view(),
        name='api_income_budget',
    ),
]
