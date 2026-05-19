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
from hasta_la_vista_money.receipts.models import PendingReceipt, Receipt, Seller
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
class ReceiptDeleterServiceProtocol(Protocol):
    """Protocol for receipt deletion service interface."""

    def delete_receipt(self, *, user: User, receipt: Receipt) -> None: ...


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


@runtime_checkable
class PendingReceiptServiceProtocol(Protocol):
    """Protocol for pending receipt service interface.

    Defines the contract for managing pending receipts across the
    background-processing lifecycle (upload → processing → ready/failed →
    review/save) and for deduplicating uploads by image hash.
    """

    def find_duplicate(
        self,
        *,
        user: User,
        image_hash: str,
    ) -> Any | None: ...

    def create_processing_job(
        self,
        *,
        user: User,
        account: Account,
        image_file: Any,
        image_hash: str,
    ) -> PendingReceipt: ...

    def attach_task_id(
        self,
        *,
        pending_receipt: PendingReceipt,
        task_id: str,
    ) -> None: ...

    def mark_ready(
        self,
        *,
        pending_receipt: PendingReceipt,
        receipt_data: dict[str, Any],
    ) -> PendingReceipt: ...

    def mark_failed(
        self,
        *,
        pending_receipt: PendingReceipt,
        error_message: str,
    ) -> PendingReceipt: ...

    def reset_for_retry(
        self,
        *,
        pending_receipt: PendingReceipt,
    ) -> PendingReceipt: ...

    def create_pending_receipt(
        self,
        *,
        user: User,
        account: Account,
        receipt_data: dict[str, Any],
    ) -> PendingReceipt: ...

    def update_pending_receipt(
        self,
        *,
        pending_receipt: PendingReceipt,
        receipt_data: dict[str, Any],
        account: Account | None = None,
    ) -> PendingReceipt: ...

    def convert_to_receipt(
        self,
        *,
        pending_receipt: PendingReceipt,
    ) -> Receipt: ...

    def delete_with_file(
        self,
        *,
        pending_receipt: PendingReceipt,
    ) -> None: ...
