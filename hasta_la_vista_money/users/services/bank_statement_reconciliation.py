from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import Category, Transaction
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
)


class InvalidReconciliationDecisionError(ValueError):
    """Raised when a statement row decision is unsupported."""


class ReconciliationDecisionConflictError(ValueError):
    """Raised when a decided row receives a different decision."""


class BankStatementReconciliationService:
    """Apply an owner decision to a probable statement duplicate."""

    @transaction.atomic
    def decide(
        self,
        row_id: int,
        decision: str,
        user_id: int,
    ) -> BankStatementRow:
        row = (
            BankStatementRow.objects.select_for_update()
            .select_related('upload', 'upload__account', 'candidate')
            .get(
                pk=row_id,
                upload__user_id=user_id,
                upload__account__user_id=user_id,
            )
        )
        if row.decision != BankStatementRow.Decision.PENDING:
            if row.decision != decision:
                raise ReconciliationDecisionConflictError(decision)
            return row

        if decision == BankStatementRow.Decision.LINKED:
            row.transaction = row.candidate
        elif decision == BankStatementRow.Decision.NEW:
            row.transaction = self._create_transaction(row)
        else:
            raise InvalidReconciliationDecisionError(decision)

        row.decision = decision
        row.decided_at = timezone.now()
        row.save(
            update_fields=['transaction', 'decision', 'decided_at'],
        )
        if not BankStatementRow.objects.filter(
            upload=row.upload,
            decision=BankStatementRow.Decision.PENDING,
        ).exists():
            row.upload.status = BankStatementUpload.Status.COMPLETED
            row.upload.save(update_fields=['status'])
        return row

    def _create_transaction(self, row: BankStatementRow) -> Transaction:
        category, _ = Category.objects.get_or_create(
            user=row.upload.user,
            name=row.suggested_category,
            type=row.transaction_type,
        )
        created = Transaction.objects.create(
            user=row.upload.user,
            account=row.upload.account,
            category=category,
            type=row.transaction_type,
            amount=row.amount,
            date=row.transaction_date,
            source_ref=row.source_ref,
            source_file_hash=(
                row.upload.file_hash if not row.source_ref else None
            ),
            source_row_position=(
                row.source_row_position if not row.source_ref else None
            ),
        )
        delta = row.amount
        if row.transaction_type == 'expense':
            delta = -delta
        account = Account.objects.select_for_update().get(
            pk=row.upload.account_id,
        )
        account.balance += Decimal(delta)
        account.save(update_fields=['balance', 'updated_at'])
        return created
