"""URL routes for transaction HTML views."""

from django.urls import path

from hasta_la_vista_money.transactions.views import (
    CategoryCreateView,
    CategoryDeleteView,
    CategoryListView,
    CategoryUpdateView,
)

app_name = 'transactions'

urlpatterns = [
    path('categories/', CategoryListView.as_view(), name='category_list'),
    path(
        'categories/create/',
        CategoryCreateView.as_view(),
        name='create_category',
    ),
    path(
        'categories/<int:pk>/update/',
        CategoryUpdateView.as_view(),
        name='update_category',
    ),
    path(
        'categories/<int:pk>/delete/',
        CategoryDeleteView.as_view(),
        name='delete_category',
    ),
]
