from django.urls import path

from hasta_la_vista_money.receipts.apis import (
    DataUrlAPIView,
    ProductAutocompleteAPIView,
    ReceiptCreateAPIView,
    ReceiptDeleteAPIView,
    ReceiptListAPIView,
    SellerAutocompleteAPIView,
    SellerCreateAPIView,
    SellerDetailAPIView,
)
from hasta_la_vista_money.receipts.views import (
    ProductByMonthView,
    ReceiptCreateView,
    ReceiptDeleteView,
    ReceiptUpdateView,
    ReceiptView,
    SellerCreateView,
    UploadImageView,
    ajax_receipts_by_group,
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
    path('update/<int:pk>/', ReceiptUpdateView.as_view(), name='update'),
    path('<int:pk>/', ReceiptDeleteView.as_view(), name='delete'),
    path(
        'delete/<int:pk>/',
        ReceiptDeleteAPIView.as_view(),
        name='delete_api',
    ),
    path(
        'list/',
        ReceiptListAPIView.as_view(),
        name='api_list',
    ),
    path(
        'create-receipt/',
        ReceiptCreateAPIView.as_view(),
        name='receipt_api_create',
    ),
    path(
        'image/',
        DataUrlAPIView.as_view(),
        name='receipt_image',
    ),
    path(
        'seller/create/',
        SellerCreateAPIView.as_view(),
        name='seller_create_api',
    ),
    path(
        'seller/<int:id>/',
        SellerDetailAPIView.as_view(),
        name='seller',
    ),
    path(
        'products',
        ProductByMonthView.as_view(),
        name='products',
    ),
    path(
        'upload/',
        UploadImageView.as_view(),
        name='upload',
    ),
    path(
        'api/seller-autocomplete/',
        SellerAutocompleteAPIView.as_view(),
        name='seller_autocomplete_api',
    ),
    path(
        'api/product-autocomplete/',
        ProductAutocompleteAPIView.as_view(),
        name='product_autocomplete_api',
    ),
    path(
        'ajax/receipts_by_group/',
        ajax_receipts_by_group,
        name='ajax_receipts_by_group',
    ),
]
