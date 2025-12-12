from django.urls import path

from hasta_la_vista_money.receipts.apis import (
    DataUrlAPIView,
    ProductAutocompleteAPIView,
    ReceiptCreateAPIView,
    ReceiptDeleteAPIView,
    ReceiptListAPIView,
    ReceiptsByGroupAPIView,
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
        'seller-autocomplete/',
        SellerAutocompleteAPIView.as_view(),
        name='seller_autocomplete_api',
    ),
    path(
        'product-autocomplete/',
        ProductAutocompleteAPIView.as_view(),
        name='product_autocomplete_api',
    ),
    path(
        'by-group/',
        ReceiptsByGroupAPIView.as_view(),
        name='by_group',
    ),
]
