from typing import TYPE_CHECKING

from django.db import transaction

from core.protocols.services import AccountServiceProtocol
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.receipts.services.receipt_creator import (
    receipt_balance_delta,
)
from hasta_la_vista_money.system.models import AuditOperationKind
from hasta_la_vista_money.system.services.audit_context import audit_operation
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.services.protocols import (
        AccountCoverageServiceProtocol,
    )
from hasta_la_vista_money.finance_account.services.financial_change_hooks import (  # noqa: E501
    note_financial_change,
)


class ReceiptDeleterService:
    """Service for deleting receipts and refunding account balance."""

    def __init__(
        self,
        account_service: AccountServiceProtocol,
        coverage_service: 'AccountCoverageServiceProtocol',
    ) -> None:
        self.account_service = account_service
        self.coverage_service = coverage_service

    @audit_operation(kind=AuditOperationKind.RECEIPT_DELETE)
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

        account = receipt.account
        receipt_date = receipt.receipt_date
        receipt.product.all().delete()
        receipt.delete()
        note_financial_change(
            coverage_service=self.coverage_service,
            changes=[(account, receipt_date)],
            moments=[receipt_date],
        )
