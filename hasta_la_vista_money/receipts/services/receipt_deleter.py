from django.db import transaction

from core.protocols.services import AccountServiceProtocol
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.receipts.services.receipt_creator import (
    receipt_balance_delta,
)
from hasta_la_vista_money.users.models import User


class ReceiptDeleterService:
    """Service for deleting receipts and refunding account balance."""

    def __init__(self, account_service: AccountServiceProtocol) -> None:
        self.account_service = account_service

    @transaction.atomic
    def delete_receipt(self, *, user: User, receipt: Receipt) -> None:
        """Delete receipt and reverse its balance effect."""
        receipt = Receipt.objects.select_for_update().get(pk=receipt.pk)
        if receipt.user_id != user.pk:
            raise Receipt.DoesNotExist
        self.account_service.apply_account_deltas(
            {
                receipt.account_id: -receipt_balance_delta(
                    receipt.operation_type,
                    receipt.total_sum,
                ),
            },
        )

        for product in receipt.product.all():
            product.delete()

        receipt.delete()
