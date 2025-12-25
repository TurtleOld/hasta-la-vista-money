"""Protocols for receipt service interfaces.

This module defines Protocol interfaces for receipt-related services,
enabling dependency injection and type checking.
"""

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from django.core.files.uploadedfile import UploadedFile
from django.forms import BaseFormSet

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.forms import ReceiptForm
from hasta_la_vista_money.receipts.models import Receipt, Seller
from hasta_la_vista_money.receipts.services.receipt_creator import (
    ReceiptCreateData,
    SellerCreateData,
)
from hasta_la_vista_money.receipts.services.receipt_import import (
    ReceiptImportResult,
)
from hasta_la_vista_money.users.models import User


@runtime_checkable
class ReceiptCreatorServiceProtocol(Protocol):
    """Protocol for receipt creation service interface.

    Defines the contract for creating receipts, both manually
    and from imported data.
    """

    def create_manual_receipt(
        self,
        *,
        user: User,
        receipt_form: ReceiptForm,
        product_formset: BaseFormSet[Any],
        seller: Seller,
    ) -> Receipt | None: ...

    def create_receipt_with_products(
        self,
        *,
        user: User,
        account: Account,
        receipt_data: ReceiptCreateData,
        seller_data: SellerCreateData,
        products_data: list[dict[str, Any]] | None = None,
        manual: bool = False,
    ) -> Receipt: ...


@runtime_checkable
class ReceiptUpdaterServiceProtocol(Protocol):
    """Protocol for receipt update service interface.

    Defines the contract for updating existing receipts
    with new data.
    """

    def update_receipt(
        self,
        *,
        user: User,
        receipt: Receipt,
        form: ReceiptForm,
        product_formset: BaseFormSet[Any],
    ) -> Receipt: ...


@runtime_checkable
class ReceiptImportServiceProtocol(Protocol):
    """Protocol for receipt import service interface.

    Defines the contract for importing receipts from uploaded images
    or other sources.
    """

    def process_uploaded_image(
        self,
        *,
        user: User,
        account: Account,
        uploaded_file: UploadedFile,
        image_analysis_function: Callable[[UploadedFile], str] | None = None,
    ) -> ReceiptImportResult: ...
