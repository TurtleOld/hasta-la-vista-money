from datetime import datetime
from typing import Final

from django.db import IntegrityError, transaction
from django.db.models import F, Max, QuerySet
from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.finance_account.repositories import (
    AccountRepository,
    TransferMoneyLogRepository,
)
from hasta_la_vista_money.finance_account.services.balance_service import (
    BalanceService,
)
from hasta_la_vista_money.finance_account.validators import (
    validate_same_currency,
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

    def __init__(
        self,
        balance_service: BalanceService,
        account_repository: AccountRepository,
        transfer_log_repository: TransferMoneyLogRepository,
    ) -> None:
        self._balance_service = balance_service
        self._account_repository = account_repository
        self._transfer_log_repository = transfer_log_repository

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

    @transaction.atomic
    def post_many(
        self,
        row_ids: list[int],
        user_id: int,
        category_id: int | None,
    ) -> list[BankStatementRow]:
        """Post rows of one direction with one category, all or nothing."""
        rows = BankStatementRow.objects.filter(
            pk__in=row_ids,
            upload__user_id=user_id,
        )
        kinds = {row.kind for row in rows}
        types = {row.transaction_type for row in rows}
        if (
            not row_ids
            or len(rows) != len(set(row_ids))
            or len(types) != 1
            or RosDorBankRowKind.OWN_C2C in kinds
        ):
            raise StatementMarkupConflictError('selection')
        with audit_operation(kind=AuditOperationKind.STATEMENT_MARKUP):
            return [
                self._decide(row_id, user_id, category_id, skip=False)
                for row_id in row_ids
            ]

    def post_transfer(
        self,
        row_id: int,
        user_id: int,
        account_id: int | None,
    ) -> BankStatementRow:
        """Close the row with a transfer to or from an own account."""
        with audit_operation(kind=AuditOperationKind.STATEMENT_MARKUP):
            return self._decide(
                row_id,
                user_id,
                None,
                skip=False,
                transfer_account_id=account_id,
                as_transfer=True,
            )

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
        transfer_account_id: int | None = None,
        as_transfer: bool = False,
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
        elif as_transfer:
            row.transfer = self._create_transfer(
                row,
                upload,
                transfer_account_id,
            )
            row.decision = BankStatementRow.Decision.TRANSFERRED
        else:
            row.transaction = self._create_movement(
                row,
                upload,
                category_id,
            )
            row.decision = BankStatementRow.Decision.NEW
        row.decided_at = timezone.now()
        row.save(
            update_fields=['transaction', 'transfer', 'decision', 'decided_at'],
        )
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
        transaction_date = row.transaction_date
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
        moment = self._moment(transaction_date)
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
    def _moment(statement_date: datetime) -> datetime:
        # The statement has no time of day: use the moment of markup.
        now = timezone.localtime()
        return datetime.combine(
            timezone.localtime(statement_date).date(),
            now.time(),
            tzinfo=now.tzinfo,
        )

    def _create_transfer(
        self,
        row: BankStatementRow,
        upload: BankStatementUpload,
        account_id: int | None,
    ) -> TransferMoneyLog:
        if (
            row.kind
            not in {RosDorBankRowKind.OWN_C2C, RosDorBankRowKind.UNKNOWN}
            or row.transaction_type is None
            or row.amount is None
            or row.transaction_date is None
        ):
            raise StatementMarkupConflictError('row')
        own = upload.account
        other = self._counterparty(row, upload, account_id)
        if other.pk == own.pk:
            raise StatementMarkupConflictError('account')
        if own.is_deposit or other.is_deposit:
            raise StatementMarkupConflictError('account')
        validate_same_currency(own, other)
        source, target = (
            (own, other)
            if row.transaction_type == TransactionType.EXPENSE
            else (other, own)
        )
        # The bank is the source of truth: no funds check.
        locked = self._balance_service.apply_account_deltas(
            {source.pk: -row.amount, target.pk: row.amount},
            check_funds=False,
        )
        return self._transfer_log_repository.create_log(
            user=upload.user,
            from_account=locked[source.pk],
            to_account=locked[target.pk],
            amount=row.amount,
            exchange_date=self._moment(row.transaction_date),
            notes=row.description,
        )

    def _counterparty(
        self,
        row: BankStatementRow,
        upload: BankStatementUpload,
        account_id: int | None,
    ) -> Account:
        """Own account of the transfer: by number, else the chosen one."""
        number = (
            row.counterparty_account
            if row.kind == RosDorBankRowKind.OWN_C2C
            else ''
        )
        if number:
            found = self._account_repository.get_by_user_and_account_number(
                upload.user,
                number,
            )
            if found is not None:
                return found
        chosen = (
            Account.objects.filter(
                pk=account_id,
                user_id=upload.user_id,
            ).first()
            if account_id is not None
            else None
        )
        if chosen is None:
            raise StatementMarkupConflictError('account')
        if number:
            if chosen.account_number:
                raise StatementMarkupConflictError('account_number')
            chosen.account_number = number
            try:
                # The unique index rejects a number another account holds.
                with transaction.atomic():
                    chosen.save(update_fields=['account_number'])
            except IntegrityError as error:
                raise StatementMarkupConflictError('account_number') from error
        return chosen

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
