from datetime import datetime
from typing import Final

from django.db import transaction
from django.db.models import F, Max, QuerySet
from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.services.balance_service import (
    BalanceService,
)
from hasta_la_vista_money.system.models import AuditOperationKind
from hasta_la_vista_money.system.services.audit_context import audit_operation
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import (
    BankStatementDecisionAudit,
    BankStatementRow,
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.services.bank_statement import (
    RosDorBankRowKind,
)
from hasta_la_vista_money.users.services.bank_statement_reconciliation import (
    BankStatementReconciliationService,
)

REFUND_CATEGORY_NAME: Final = 'Возвраты'


class StatementMarkupConflictError(ValueError):
    """Raised when a row cannot be marked up as requested."""


class StatementMarkupService:
    """Post or skip RosDorBank statement rows after user markup."""

    def __init__(self, balance_service: BalanceService) -> None:
        self._balance_service = balance_service

    @staticmethod
    def pending_rows(upload: BankStatementUpload) -> QuerySet[BankStatementRow]:
        return BankStatementRow.objects.filter(
            upload=upload,
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
        ).order_by('transaction_date', 'pk')

    @staticmethod
    def categories(user: User, transaction_type: str) -> list[Category]:
        """Return the user's categories, recently used first."""
        return list(
            Category.objects.filter(
                user=user,
                type=transaction_type,
                system_kind='',
            )
            .annotate(last_used=Max('transactions__date'))
            .order_by(F('last_used').desc(nulls_last=True), 'name'),
        )

    def post(
        self,
        row_id: int,
        user_id: int,
        category_id: int | None,
    ) -> BankStatementRow:
        """Post the row as a movement now, as one markup operation."""
        with audit_operation(kind=AuditOperationKind.STATEMENT_MARKUP):
            return self._decide(row_id, user_id, category_id, skip=False)

    def skip(self, row_id: int, user_id: int) -> BankStatementRow:
        """Skip the row without touching the balance."""
        with audit_operation(kind=AuditOperationKind.STATEMENT_MARKUP):
            return self._decide(row_id, user_id, None, skip=True)

    @transaction.atomic
    def _decide(
        self,
        row_id: int,
        user_id: int,
        category_id: int | None,
        *,
        skip: bool,
    ) -> BankStatementRow:
        upload = (
            BankStatementUpload.objects.select_for_update()
            .select_related('account')
            .get(statement_rows__pk=row_id, user_id=user_id)
        )
        row = BankStatementRow.objects.select_for_update().get(
            pk=row_id,
            upload=upload,
        )
        if row.decision != BankStatementRow.Decision.AWAITING_MARKUP:
            raise StatementMarkupConflictError(row.decision)
        if timezone.now() >= upload.expires_at:
            raise StatementMarkupConflictError('expired')

        if skip:
            row.decision = BankStatementRow.Decision.SKIPPED
        else:
            row.transaction = self._create_movement(
                row,
                upload,
                category_id,
            )
            row.decision = BankStatementRow.Decision.NEW
        row.decided_at = timezone.now()
        row.save(update_fields=['transaction', 'decision', 'decided_at'])
        BankStatementDecisionAudit.objects.create(
            row=row,
            actor_id=user_id,
            decision=row.decision,
            transaction=row.transaction,
        )
        BankStatementReconciliationService.refresh_outcome_counts(upload)
        if not self.pending_rows(upload).exists():
            upload.status = BankStatementUpload.Status.COMPLETED
            upload.save(update_fields=['status'])
        return row

    def _create_movement(
        self,
        row: BankStatementRow,
        upload: BankStatementUpload,
        category_id: int | None,
    ) -> Transaction:
        transaction_type = row.transaction_type
        if (
            transaction_type is None
            or row.amount is None
            or row.transaction_date is None
        ):
            raise StatementMarkupConflictError('row')
        account = upload.account
        if account.is_archived or account.is_deposit:
            raise StatementMarkupConflictError('account')
        if (
            transaction_type == TransactionType.INCOME
            and account.type_account in constants.CREDIT_ACCOUNT_TYPES
        ):
            raise StatementMarkupConflictError(
                constants.CREDIT_CARD_INCOME_BAN,
            )
        category = self._category(row, upload.user, category_id)
        # The statement has no time of day: use the moment of markup.
        now = timezone.localtime()
        moment = datetime.combine(
            timezone.localtime(row.transaction_date).date(),
            now.time(),
            tzinfo=now.tzinfo,
        )
        created = Transaction.objects.create(
            user=upload.user,
            account=account,
            category=category,
            type=transaction_type,
            amount=row.amount,
            date=moment,
            description=row.description,
            source_ref=row.source_ref,
            source_file_hash=(upload.file_hash if not row.source_ref else None),
            source_row_position=(
                row.source_row_position if not row.source_ref else None
            ),
        )
        delta = row.amount
        if transaction_type == TransactionType.EXPENSE:
            delta = -delta
        # The bank is the source of truth: no funds check.
        self._balance_service.apply_balance_delta(
            account,
            delta,
            check_funds=False,
        )
        return created

    @staticmethod
    def _category(
        row: BankStatementRow,
        user: User,
        category_id: int | None,
    ) -> Category:
        if category_id is not None:
            category = Category.objects.filter(
                pk=category_id,
                user=user,
                type=row.transaction_type,
                system_kind='',
            ).first()
            if category is None:
                raise StatementMarkupConflictError('category')
            return category
        if row.kind == RosDorBankRowKind.CANCEL:
            return Category.objects.get_or_create(
                user=user,
                name=REFUND_CATEGORY_NAME,
                type=row.transaction_type,
            )[0]
        raise StatementMarkupConflictError('category')
