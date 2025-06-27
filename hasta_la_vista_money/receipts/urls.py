from django.urls import path
from hasta_la_vista_money.receipts.apis import (
    DataUrlAPIView,
    ReceiptCreateAPIView,
    ReceiptListAPIView,
    SellerCreateAPIView,
    SellerDetailAPIView,
    SellerAutocompleteAPIView,
    ProductAutocompleteAPIView,
)
from hasta_la_vista_money.receipts.views import (
    ProductByMonthView,
    ReceiptCreateView,
    ReceiptDeleteView,
    ReceiptView,
    SellerCreateView,
    UploadImageView,
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
]
