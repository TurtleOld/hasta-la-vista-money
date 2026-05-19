from django.db import transaction

from core.protocols.services import AccountServiceProtocol
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.users.services.cache import (
    invalidate_user_detailed_statistics_cache,
)


class ReceiptDeleterService:
    """Service for deleting receipts and refunding account balance."""

    def __init__(self, account_service: AccountServiceProtocol) -> None:
        self.account_service = account_service

    @transaction.atomic
    def delete_receipt(self, *, user: User, receipt: Receipt) -> None:
        """Delete receipt and refund its total through BalanceService."""
        self.account_service.refund_to_account(
            receipt.account,
            receipt.total_sum,
        )

        for product in receipt.product.all():
            product.delete()

        receipt.delete()
        transaction.on_commit(
            lambda: invalidate_user_detailed_statistics_cache(user.pk),
        )
