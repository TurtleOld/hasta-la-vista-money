from django.urls import path

from hasta_la_vista_money.loan.views import (
    LoanCreateView,
    LoanDeleteView,
    LoanView,
    PaymentMakeCreateView,
)

app_name = 'loan'
urlpatterns = [
    path('', LoanView.as_view(), name='list'),
    path('create/', LoanCreateView.as_view(), name='create'),
    path('delete/<int:pk>', LoanDeleteView.as_view(), name='delete'),
    path(
        'payment/create/',
        PaymentMakeCreateView.as_view(),
        name='payment_create',
    ),
]
