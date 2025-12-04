from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from django.core.files.uploadedfile import UploadedFile
from django.forms import BaseFormSet

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.forms import ReceiptForm
from hasta_la_vista_money.receipts.models import Receipt, Seller
from hasta_la_vista_money.receipts.services.receipt_import import (
    ReceiptImportResult,
)
from hasta_la_vista_money.users.models import User


@runtime_checkable
class ReceiptCreatorServiceProtocol(Protocol):
    def create_manual_receipt(
        self,
        *,
        user: User,
        receipt_form: ReceiptForm,
        product_formset: BaseFormSet[Any],
        seller: Seller,
    ) -> Receipt | None: ...
    
    def create_receipt_from_json(
        self,
        *,
        user: User,
        account: Account,
        data: dict[str, Any],
    ) -> Receipt: ...


@runtime_checkable
class ReceiptUpdaterServiceProtocol(Protocol):
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
    def process_uploaded_image(
        self,
        *,
        user: User,
        account: Account,
        uploaded_file: UploadedFile,
        analyze_func: Callable[[UploadedFile], str] | None = None,
    ) -> ReceiptImportResult: ...
