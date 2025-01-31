from django.urls import path
from hasta_la_vista_money.expense.views import (
    ExpenseCategoryCreateView,
    ExpenseCategoryDeleteView,
    ExpenseCategoryView,
    ExpenseCopyView,
    ExpenseCreateView,
    ExpenseDeleteView,
    ExpenseUpdateView,
    ExpenseView,
)

app_name = 'expense'
urlpatterns = [
    path('', ExpenseView.as_view(), name='list'),
    path('create/', ExpenseCreateView.as_view(), name='create'),
    path('change/<int:pk>/', ExpenseUpdateView.as_view(), name='change'),
    path('delete/<int:pk>/', ExpenseDeleteView.as_view(), name='delete'),
    path(
        'category/list',
        ExpenseCategoryView.as_view(),
        name='category_list',
    ),
    path(
        'category/<int:pk>/',
        ExpenseCategoryDeleteView.as_view(),
        name='delete_category_expense',
    ),
    path(
        'create/category/',
        ExpenseCategoryCreateView.as_view(),
        name='create_category',
    ),
    path(
        '<int:pk>/copy/',
        ExpenseCopyView.as_view(),
        name='expense_copy',
    ),
]
