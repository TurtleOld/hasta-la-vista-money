from django.urls import path
from hasta_la_vista_money.income.views import (
    DeleteIncomeCategoryView,
    IncomeChangeView,
    IncomeDeleteView,
    IncomeView,
)

app_name = 'income'
urlpatterns = [
    path('', IncomeView.as_view(), name='list'),
    path('<int:pk>/', IncomeChangeView.as_view(), name='change'),
    path('<int:pk>/', IncomeDeleteView.as_view(), name='delete_income'),
    path(
        'category/<int:pk>/',
        DeleteIncomeCategoryView.as_view(),
        name='delete_category_income',
    ),
]
