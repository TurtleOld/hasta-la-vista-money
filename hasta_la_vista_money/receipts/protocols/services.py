"""Protocols for receipt service interfaces.

This module defines Protocol interfaces for receipt-related services,
enabling dependency injection and type checking.
"""

from collections.abc import Iterable
from typing import Any, Protocol, runtime_checkable

from django.forms import BaseFormSet

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.forms import ReceiptForm
from hasta_la_vista_money.receipts.models import (
    PendingReceipt,
    Product,
    ProductCategory,
    Receipt,
    ReceiptProcessingLog,
    Seller,
)
from hasta_la_vista_money.receipts.services.receipt_creator import (
    ReceiptCreateData,
    SellerCreateData,
)
from hasta_la_vista_money.users.models import User


@runtime_checkable
class ReceiptCategoryModelTransportProtocol(Protocol):
    """Transport boundary for structured product-category requests."""

    def complete(
        self,
        *,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return an external chat-completion response."""
        ...


@runtime_checkable
class ExternalProductCategoryServiceProtocol(Protocol):
    """Contract for the optional external product-category fallback."""

    @property
    def enabled(self) -> bool:
        """Return whether the external transport is configured."""
        ...

    def categorize_product(self, product: Product) -> bool:
        """Try to replace the default category for one product."""
        ...


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
        seller_data: SellerCreateData | None = None,
        seller_id: int | None = None,
        products_data: Iterable[dict[str, Any]] | None = None,
        manual: bool = False,
        requires_attention: bool = False,
        attention_reason: str = '',
        allow_insufficient_funds: bool = False,
    ) -> Receipt: ...


@runtime_checkable
class ReceiptProcessingServiceProtocol(Protocol):
    """Protocol for automatic receipt processing journal operations."""

    def find_duplicate(
        self,
        *,
        user: User,
        image_hash: str | None = None,
        fiscal_key: str | None = None,
    ) -> Receipt | ReceiptProcessingLog | None: ...

    def create_image_job(
        self,
        *,
        user: User,
        account: Account,
        image_file: Any,
        image_hash: str,
    ) -> ReceiptProcessingLog: ...

    def create_qr_job(
        self,
        *,
        user: User,
        account: Account,
        qr_raw: str,
        image_hash: str,
        fiscal_key: str,
    ) -> ReceiptProcessingLog: ...

    def create_duplicate_qr_job(
        self,
        *,
        user: User,
        account: Account,
        qr_raw: str,
        image_hash: str,
        fiscal_key: str,
    ) -> ReceiptProcessingLog: ...

    def attach_task_id(
        self,
        *,
        log: ReceiptProcessingLog,
        task_id: str,
    ) -> None: ...

    def claim_fiscal_key(
        self,
        *,
        log: ReceiptProcessingLog,
        fiscal_key: str,
        task_id: str,
    ) -> bool: ...

    def mark_failed(
        self,
        *,
        log: ReceiptProcessingLog,
        error_message: str,
        task_id: str,
    ) -> None: ...

    def complete(
        self,
        *,
        log: ReceiptProcessingLog,
        receipt_data: dict[str, Any],
        task_id: str,
    ) -> Receipt: ...

    def reset_for_retry(
        self,
        *,
        log: ReceiptProcessingLog,
    ) -> ReceiptProcessingLog: ...

    def get_for_user(
        self,
        *,
        user: User,
        log_id: int,
    ) -> ReceiptProcessingLog | None: ...

    def get_visible_for_user(self, *, user: User) -> Any: ...

    def get_unnotified_completed(
        self,
        *,
        user: User,
    ) -> list[ReceiptProcessingLog]: ...

    def is_insufficient_at_conducting(self, *, receipt: Receipt) -> bool: ...


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
class ProductCategoryCorrectionServiceProtocol(Protocol):
    """Contract for remembering human product-category corrections."""

    def apply_correction(
        self,
        *,
        user: User,
        product_name: str,
        category: ProductCategory | None,
        exclude_product_ids: Iterable[int] = (),
    ) -> None: ...


@runtime_checkable
class ReceiptDeleterServiceProtocol(Protocol):
    """Protocol for receipt deletion service interface."""

    def delete_receipt(self, *, user: User, receipt: Receipt) -> None: ...


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
        image_hash: str | None = None,
        fiscal_key: str | None = None,
    ) -> Any | None: ...

    def create_processing_job(
        self,
        *,
        user: User,
        account: Account,
        image_file: Any,
        image_hash: str,
        fiscal_key: str | None = None,
    ) -> PendingReceipt: ...

    def create_processing_job_from_qr(
        self,
        *,
        user: User,
        account: Account,
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
        task_id: str | None = None,
    ) -> bool: ...

    def mark_failed(
        self,
        *,
        pending_receipt: PendingReceipt,
        error_message: str,
        task_id: str | None = None,
    ) -> bool: ...

    def claim_fiscal_key(
        self,
        *,
        pending_receipt: PendingReceipt,
        fiscal_key: str,
        task_id: str,
    ) -> bool: ...

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
