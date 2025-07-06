from django.urls import path
from hasta_la_vista_money.income.views import (
    IncomeCategoryCreateView,
    IncomeCategoryDeleteView,
    IncomeCategoryView,
    IncomeCopyView,
    IncomeCreateView,
    IncomeDataAjaxView,
    IncomeDeleteView,
    IncomeGetAjaxView,
    IncomeGroupAjaxView,
    IncomeUpdateView,
    IncomeView,
)

app_name = 'income'
urlpatterns = [
    path('', IncomeView.as_view(), name='list'),
    path('create/', IncomeCreateView.as_view(), name='create'),
    path(
        'category/list',
        IncomeCategoryView.as_view(),
        name='category_list',
    ),
    path(
        'create/category/',
        IncomeCategoryCreateView.as_view(),
        name='create_category',
    ),
    path('change/<int:pk>/', IncomeUpdateView.as_view(), name='change'),
    path(
        'delete/<int:pk>/',
        IncomeDeleteView.as_view(),
        name='delete_income',
    ),
    path(
        'category/<int:pk>/',
        IncomeCategoryDeleteView.as_view(),
        name='delete_category_income',
    ),
    path(
        '<int:pk>/copy/',
        IncomeCopyView.as_view(),
        name='income_copy',
    ),
    path(
        'ajax/income_by_group/',
        IncomeGroupAjaxView.as_view(),
        name='ajax_income_by_group',
    ),
    path('ajax/income_data/', IncomeDataAjaxView.as_view(), name='ajax_income_data'),
    path('get/<int:pk>/', IncomeGetAjaxView.as_view(), name='get_income'),
]
