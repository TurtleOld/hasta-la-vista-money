from django.urls import path
from hasta_la_vista_money.receipts.apis import (
    ReceiptCreateAPIView,
    ReceiptListAPIView,
    SellerCreateAPIView,
    SellerListAPIView,
)
from hasta_la_vista_money.receipts.views import (
    ProductByMonthView,
    ReceiptCreateView,
    ReceiptDeleteView,
    ReceiptView,
    SellerCreateView,
)

app_name = 'receipts'
urlpatterns = [
    path('', ReceiptView.as_view(), name='list'),
    path('create/', ReceiptCreateView.as_view(), name='create'),
    path(
        'create_seller/',
        SellerCreateView.as_view(),
        name='create_seller',
    ),
    path('<int:pk>/', ReceiptDeleteView.as_view(), name='delete'),
    path(
        'list/',
        ReceiptListAPIView.as_view(),
        name='api_list',
    ),
    path(
        'api/create',
        ReceiptCreateAPIView.as_view(),
        name='receipt_api_create',
    ),
    path(
        'customer/api/create',
        SellerCreateAPIView.as_view(),
        name='api_list',
    ),
    path(
        'seller/<int:id>',
        SellerListAPIView.as_view(),
        name='seller',
    ),
    path(
        'products',
        ProductByMonthView.as_view(),
        name='products',
    ),
]
