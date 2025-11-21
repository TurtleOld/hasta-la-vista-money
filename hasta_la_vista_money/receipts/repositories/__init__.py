"""Репозитории для receipts модуля."""

from hasta_la_vista_money.receipts.repositories.product_repository import (
    ProductRepository,
)
from hasta_la_vista_money.receipts.repositories.receipt_repository import (
    ReceiptRepository,
)
from hasta_la_vista_money.receipts.repositories.seller_repository import (
    SellerRepository,
)

__all__ = [
    'ProductRepository',
    'ReceiptRepository',
    'SellerRepository',
]
