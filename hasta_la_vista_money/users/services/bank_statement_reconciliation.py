from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db import DatabaseError, transaction
from django.db.models import Count, QuerySet
from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.system.models import AuditOperationKind
from hasta_la_vista_money.system.services.audit_context import audit_operation
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import (
    BankStatementCandidate,
    BankStatementDecisionAudit,
    BankStatementRow,
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.services.statement_transfer_matching import (
    find_mirroring_transfers,
    local_row_date,
)


class InvalidReconciliationDecisionError(ValueError):
    """Raised when a statement row decision is unsupported."""


class ReconciliationDecisionConflictError(ValueError):
    """Raised when a decided row receives a different decision."""


class StaleStatementCandidateError(ValueError):
    """Raised when a selected candidate is no longer current."""


class ReconciliationExpiredError(ValueError):
    """Raised when a statement reconciliation deadline has passed."""


class AmbiguousStatementCandidateError(ValueError):
    """Raised when safe automatic linking has multiple current candidates."""


@dataclass(frozen=True)
class BulkDecisionResult:
    """Represent the outcome of one independently processed statement row."""

    row_id: int
    outcome: str

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the result."""
        return asdict(self)


class BankStatementReconciliationService:
    """Apply an owner decision to a probable statement duplicate."""

    @staticmethod
    def upload_history(user_id: int) -> QuerySet[BankStatementUpload]:
        return BankStatementUpload.objects.filter(
            user_id=user_id,
            account__user_id=user_id,
        ).select_related('account')[:10]

    @staticmethod
    def reconciliation_rows(
        upload: BankStatementUpload,
        outcome: str,
    ) -> QuerySet[BankStatementRow]:
        valid_outcomes = {
            BankStatementRow.Decision.PENDING,
            BankStatementRow.Decision.LINKED,
            BankStatementRow.Decision.NEW,
            BankStatementRow.Decision.NEEDS_TRANSFER,
            BankStatementRow.Decision.TRANSFERRED,
            BankStatementRow.Decision.NOT_A_PAYMENT,
            BankStatementRow.Decision.EXPIRED,
        }
        decision = (
            outcome
            if outcome in valid_outcomes
            else BankStatementRow.Decision.PENDING
        )
        return (
            BankStatementRow.objects.filter(
                upload=upload,
                decision=decision,
            )
            .prefetch_related(
                'candidates__transaction__category',
                'candidates__transfer__from_account',
                'candidates__transfer__to_account',
            )
            .order_by('transaction_date', 'pk')
        )

    def decide(
        self,
        row_id: int,
        decision: str,
        user_id: int,
        candidate_id: int | None = None,
    ) -> BankStatementRow:
        """Apply one owner decision to one row, as its own audit operation."""
        with audit_operation(
            kind=AuditOperationKind.STATEMENT_IMPORT_RESOLUTION,
        ):
            return self._decide(row_id, decision, user_id, candidate_id)

    @transaction.atomic
    def _decide(
        self,
        row_id: int,
        decision: str,
        user_id: int,
        candidate_id: int | None = None,
    ) -> BankStatementRow:
        upload = self._lock_upload(row_id, user_id)
        row = (
            BankStatementRow.objects.select_for_update()
            .select_related('upload__account')
            .get(
                pk=row_id,
                upload=upload,
            )
        )
        row.upload = upload
        if row.decision != BankStatementRow.Decision.PENDING:
            if row.decision != decision:
                raise ReconciliationDecisionConflictError(decision)
            if decision == BankStatementRow.Decision.LINKED:
                movement = self._validated_candidate(row, candidate_id)
                if not self._row_links_movement(row, movement):
                    raise ReconciliationDecisionConflictError(candidate_id)
            return row
        if timezone.now() >= row.upload.expires_at:
            raise ReconciliationExpiredError(row_id)

        if decision == BankStatementRow.Decision.LINKED:
            movement = self._validated_candidate(row, candidate_id)
            self._link_movement(row, movement)
        elif decision == BankStatementRow.Decision.NEW:
            row.transaction = self._create_transaction(row)
            row.transfer = None
        else:
            raise InvalidReconciliationDecisionError(decision)

        row.decision = decision
        row.decided_at = timezone.now()
        row.save(
            update_fields=[
                'transaction',
                'transfer',
                'decision',
                'decided_at',
            ],
        )
        BankStatementDecisionAudit.objects.create(
            row=row,
            actor_id=user_id,
            decision=decision,
            transaction=row.transaction,
            transfer=row.transfer,
        )
        self.refresh_outcome_counts(upload)
        if not BankStatementRow.objects.filter(
            upload=row.upload,
            decision=BankStatementRow.Decision.PENDING,
        ).exists():
            upload.status = BankStatementUpload.Status.COMPLETED
            upload.save(update_fields=['status'])
        return row

    @transaction.atomic
    def revise_linked_to_new(
        self,
        row_id: int,
        user_id: int,
    ) -> BankStatementRow:
        """Replace a linked decision with one newly imported transaction."""
        with audit_operation(
            kind=AuditOperationKind.STATEMENT_IMPORT_RESOLUTION,
        ):
            return self._revise_linked_to_new(row_id, user_id)

    def _revise_linked_to_new(
        self,
        row_id: int,
        user_id: int,
    ) -> BankStatementRow:
        upload = self._lock_upload(row_id, user_id)
        row = (
            BankStatementRow.objects.select_for_update()
            .select_related('upload__account')
            .get(
                pk=row_id,
                upload=upload,
            )
        )
        row.upload = upload
        if row.decision == BankStatementRow.Decision.NEW:
            return row
        if row.decision != BankStatementRow.Decision.LINKED:
            raise ReconciliationDecisionConflictError(row.decision)
        if timezone.now() >= row.upload.expires_at:
            raise ReconciliationExpiredError(row_id)

        previous_transaction = row.transaction
        previous_transfer = row.transfer
        row.transaction = self._create_transaction(row)
        row.transfer = None
        row.decision = BankStatementRow.Decision.NEW
        row.decided_at = timezone.now()
        row.save(
            update_fields=[
                'transaction',
                'transfer',
                'decision',
                'decided_at',
            ],
        )
        BankStatementDecisionAudit.objects.create(
            row=row,
            actor_id=user_id,
            decision=row.decision,
            previous_transaction=previous_transaction,
            previous_transfer=previous_transfer,
            transaction=row.transaction,
        )
        self.refresh_outcome_counts(upload)
        return row

    def bulk_decide(
        self,
        row_ids: list[int],
        decision: str,
        user_id: int,
        upload_id: int,
    ) -> list[BulkDecisionResult]:
        """Apply a decision independently to each selected statement row.

        One audit operation covers the whole batch, set once outside the
        per-row loop — the rows share one user action even though each is
        decided independently.
        """
        results = []
        with audit_operation(
            kind=AuditOperationKind.STATEMENT_IMPORT_RESOLUTION,
        ):
            for row_id in dict.fromkeys(row_ids):
                try:
                    BankStatementRow.objects.only('pk').get(
                        pk=row_id,
                        upload_id=upload_id,
                        upload__user_id=user_id,
                        upload__account__user_id=user_id,
                    )
                    if decision == BankStatementRow.Decision.LINKED:
                        self._decide_linked_if_unique(
                            row_id,
                            user_id,
                            upload_id,
                        )
                    else:
                        self._decide(row_id, decision, user_id)
                    results.append(BulkDecisionResult(row_id, decision))
                except BankStatementRow.DoesNotExist:
                    results.append(BulkDecisionResult(row_id, 'not_found'))
                except StaleStatementCandidateError:
                    results.append(BulkDecisionResult(row_id, 'stale'))
                except AmbiguousStatementCandidateError:
                    results.append(BulkDecisionResult(row_id, 'ambiguous'))
                except ReconciliationExpiredError:
                    results.append(BulkDecisionResult(row_id, 'expired'))
                except (
                    InvalidReconciliationDecisionError,
                    ReconciliationDecisionConflictError,
                ):
                    results.append(BulkDecisionResult(row_id, 'conflict'))
                except DatabaseError:
                    results.append(BulkDecisionResult(row_id, 'error'))
        return results

    @transaction.atomic
    def _decide_linked_if_unique(
        self,
        row_id: int,
        user_id: int,
        upload_id: int,
    ) -> BankStatementRow:
        upload = self._lock_upload(row_id, user_id, upload_id)
        row = (
            BankStatementRow.objects.select_for_update()
            .select_related('upload__account')
            .get(
                pk=row_id,
                upload=upload,
            )
        )
        row.upload = upload
        if row.decision == BankStatementRow.Decision.LINKED:
            return row
        candidate_ids = [
            candidate.pk
            for candidate in row.candidates.select_related(
                'transaction',
                'transfer',
            )
            if self._candidate_is_current(row, candidate)
        ]
        if len(candidate_ids) > 1:
            raise AmbiguousStatementCandidateError(row_id)
        if not candidate_ids:
            raise StaleStatementCandidateError(row_id)
        return self._decide(
            row_id,
            BankStatementRow.Decision.LINKED,
            user_id,
            candidate_ids[0],
        )

    @staticmethod
    def _lock_upload(
        row_id: int,
        user_id: int,
        upload_id: int | None = None,
    ) -> BankStatementUpload:
        uploads = BankStatementUpload.objects.select_for_update().filter(
            statement_rows__pk=row_id,
            user_id=user_id,
            account__user_id=user_id,
        )
        if upload_id is not None:
            uploads = uploads.filter(pk=upload_id)
        return uploads.get()

    @staticmethod
    def refresh_outcome_counts(upload: BankStatementUpload) -> None:
        decisions = (
            BankStatementRow.objects.filter(upload=upload)
            .values(
                'decision',
            )
            .annotate(count=Count('pk'))
        )
        counts = {item['decision']: item['count'] for item in decisions}
        upload.linked_count = counts.get(
            BankStatementRow.Decision.LINKED,
            0,
        )
        upload.awaiting_decision_count = counts.get(
            BankStatementRow.Decision.PENDING,
            0,
        )
        upload.needs_transfer_count = counts.get(
            BankStatementRow.Decision.NEEDS_TRANSFER,
            0,
        )
        upload.expired_count = counts.get(
            BankStatementRow.Decision.EXPIRED,
            0,
        )
        upload.imported_count = (
            upload.income_count
            + upload.expense_count
            + counts.get(BankStatementRow.Decision.NEW, 0)
        )
        upload.save(
            update_fields=[
                'linked_count',
                'awaiting_decision_count',
                'needs_transfer_count',
                'expired_count',
                'imported_count',
            ],
        )

    def _validated_candidate(
        self,
        row: BankStatementRow,
        candidate_id: int | None,
    ) -> Transaction | TransferMoneyLog:
        if candidate_id is None:
            raise InvalidReconciliationDecisionError('candidate')
        candidate = (
            BankStatementCandidate.objects.filter(
                pk=candidate_id,
                row=row,
            )
            .select_related('transaction', 'transfer')
            .first()
        )
        if candidate is None or not self._candidate_is_current(row, candidate):
            raise StaleStatementCandidateError(candidate_id)
        movement = candidate.transaction or candidate.transfer
        if movement is None:
            raise StaleStatementCandidateError(candidate_id)
        return movement

    @staticmethod
    def _row_links_movement(
        row: BankStatementRow,
        movement: Transaction | TransferMoneyLog,
    ) -> bool:
        if isinstance(movement, TransferMoneyLog):
            return row.transfer_id == movement.pk
        return row.transaction_id == movement.pk

    @staticmethod
    def _link_movement(
        row: BankStatementRow,
        movement: Transaction | TransferMoneyLog,
    ) -> None:
        if isinstance(movement, TransferMoneyLog):
            row.transfer = movement
            row.transaction = None
        else:
            row.transaction = movement
            row.transfer = None

    def _candidate_is_current(
        self,
        row: BankStatementRow,
        candidate: BankStatementCandidate,
    ) -> bool:
        transaction = candidate.transaction
        if transaction is not None:
            return self._transaction_is_current(row, transaction)
        transfer = candidate.transfer
        if transfer is not None:
            return self._transfer_is_current(row, transfer)
        return False

    @staticmethod
    def _movement_bounds(
        row: BankStatementRow,
    ) -> tuple[str, Decimal, datetime] | None:
        transaction_type = row.transaction_type
        amount = row.amount
        transaction_date = row.transaction_date
        if (
            transaction_type is None
            or amount is None
            or transaction_date is None
        ):
            return None
        return transaction_type, amount, transaction_date

    def _transaction_is_current(
        self,
        row: BankStatementRow,
        candidate: Transaction,
    ) -> bool:
        bounds = self._movement_bounds(row)
        if bounds is None:
            return False
        transaction_type, amount, transaction_date = bounds
        date_matches = candidate.date == transaction_date
        if row.match_calendar_date:
            date_matches = (
                timezone.localtime(candidate.date).date()
                == timezone.localtime(transaction_date).date()
            )
        return bool(
            candidate.account_id == row.upload.account_id
            and candidate.user_id == row.upload.user_id
            and candidate.type == transaction_type
            and candidate.amount == amount
            and date_matches,
        )

    def _transfer_is_current(
        self,
        row: BankStatementRow,
        transfer: TransferMoneyLog,
    ) -> bool:
        bounds = self._movement_bounds(row)
        if bounds is None:
            return False
        transaction_type, amount, transaction_date = bounds
        return (
            find_mirroring_transfers(
                account=row.upload.account,
                user=row.upload.user,
                transaction_type=transaction_type,
                amount=amount,
                row_date=local_row_date(transaction_date),
                exclude_row_id=row.pk,
            )
            .filter(pk=transfer.pk)
            .exists()
        )

    def current_candidates(
        self,
        row: BankStatementRow,
    ) -> QuerySet[Transaction]:
        bounds = self._movement_bounds(row)
        if bounds is None:
            return Transaction.objects.none()
        transaction_type, amount, transaction_date = bounds
        candidates = Transaction.objects.filter(
            account=row.upload.account,
            user=row.upload.user,
            type=transaction_type,
            amount=amount,
        )
        if row.match_calendar_date:
            return candidates.filter(
                date__date=local_row_date(transaction_date),
            ).order_by('date', 'pk')
        return candidates.filter(date=transaction_date).order_by(
            'date',
            'pk',
        )

    def _create_transaction(self, row: BankStatementRow) -> Transaction:
        transaction_type = row.transaction_type
        amount = row.amount
        transaction_date = row.transaction_date
        if (
            transaction_type is None
            or amount is None
            or transaction_date is None
        ):
            raise InvalidReconciliationDecisionError('expired_row')
        category, _ = Category.objects.get_or_create(
            user=row.upload.user,
            name=row.suggested_category,
            type=transaction_type,
        )
        account = Account.objects.select_for_update().get(
            pk=row.upload.account_id,
        )
        if account.is_archived or account.is_deposit:
            raise InvalidReconciliationDecisionError('account')
        if (
            transaction_type == TransactionType.INCOME
            and account.type_account in constants.CREDIT_ACCOUNT_TYPES
        ):
            raise InvalidReconciliationDecisionError(
                constants.CREDIT_CARD_INCOME_BAN,
            )
        created = Transaction.objects.create(
            user=row.upload.user,
            account=row.upload.account,
            category=category,
            type=transaction_type,
            amount=amount,
            date=transaction_date,
            description=row.description,
            source_ref=row.source_ref,
            source_file_hash=(
                row.upload.file_hash if not row.source_ref else None
            ),
            source_row_position=(
                row.source_row_position if not row.source_ref else None
            ),
        )
        delta = amount
        if transaction_type == 'expense':
            delta = -delta
        account.balance += Decimal(delta)
        account.save(update_fields=['balance', 'updated_at'])
        return created

    def pending_transfer_rows(
        self,
        account: Account,
    ) -> QuerySet[BankStatementRow]:
        """Return unperformed repayments imported for a credit account."""
        return (
            BankStatementRow.objects.filter(
                upload__account=account,
                decision=BankStatementRow.Decision.NEEDS_TRANSFER,
            )
            .select_related('upload__account')
            .order_by('transaction_date', 'pk')
        )

    def pending_transfers_for_user(
        self,
        user: User,
    ) -> QuerySet[BankStatementRow]:
        """Return all unperformed repayments of a user's credit accounts."""
        return (
            BankStatementRow.objects.filter(
                upload__user_id=user.pk,
                upload__account__user_id=user.pk,
                upload__account__type_account__in=(
                    constants.CREDIT_ACCOUNT_TYPES
                ),
                decision=BankStatementRow.Decision.NEEDS_TRANSFER,
            )
            .select_related('upload__account')
            .order_by('transaction_date', 'pk')
        )

    def mark_not_payment(self, row_id: int, user_id: int) -> BankStatementRow:
        """Close an unperformed repayment row without creating a movement."""
        with audit_operation(
            kind=AuditOperationKind.STATEMENT_IMPORT_RESOLUTION,
        ):
            return self._mark_not_payment(row_id, user_id)

    @transaction.atomic
    def _mark_not_payment(
        self,
        row_id: int,
        user_id: int,
    ) -> BankStatementRow:
        row = (
            BankStatementRow.objects.select_for_update()
            .select_related('upload')
            .get(
                pk=row_id,
                upload__user_id=user_id,
                upload__account__user_id=user_id,
            )
        )
        if row.decision == BankStatementRow.Decision.NOT_A_PAYMENT:
            return row
        if row.decision != BankStatementRow.Decision.NEEDS_TRANSFER:
            raise ReconciliationDecisionConflictError(row.decision)
        row.decision = BankStatementRow.Decision.NOT_A_PAYMENT
        row.decided_at = timezone.now()
        row.save(update_fields=['decision', 'decided_at'])
        BankStatementDecisionAudit.objects.create(
            row=row,
            actor_id=user_id,
            decision=row.decision,
        )
        self.refresh_outcome_counts(row.upload)
        return row

    def settle_pending_transfers(self, account: Account) -> int:
        """Close unperformed repayments matched by existing transfers.

        A transfer closes at most one row: its amount must match and its
        date must be within one day of the statement row.
        """
        with audit_operation(
            kind=AuditOperationKind.STATEMENT_IMPORT_RESOLUTION,
        ):
            return self._settle_pending_transfers(account)

    def settle_transfers_for_user(self, user: User) -> int:
        """Auto-close pending repayments across a user's credit accounts."""
        total = 0
        for account in Account.objects.filter(
            user=user,
            type_account__in=constants.CREDIT_ACCOUNT_TYPES,
        ):
            total += self.settle_pending_transfers(account)
        return total

    @transaction.atomic
    def _settle_pending_transfers(self, account: Account) -> int:
        if account.type_account not in constants.CREDIT_ACCOUNT_TYPES:
            return 0
        rows = list(
            BankStatementRow.objects.select_for_update()
            .filter(
                upload__account=account,
                decision=BankStatementRow.Decision.NEEDS_TRANSFER,
            )
            .order_by('transaction_date', 'pk'),
        )
        if not rows:
            return 0
        used_ids = set(
            BankStatementRow.objects.filter(
                transfer__isnull=False,
                upload__account=account,
            ).values_list('transfer_id', flat=True),
        )
        settled_upload_ids: set[int] = set()
        settled = 0
        for row in rows:
            if row.amount is None or row.transaction_date is None:
                continue
            row_date = timezone.localtime(row.transaction_date).date()
            transfer = (
                TransferMoneyLog.objects.filter(
                    user_id=account.user_id,
                    to_account=account,
                    amount=row.amount,
                    exchange_date__date__gte=row_date - timedelta(days=1),
                    exchange_date__date__lte=row_date + timedelta(days=1),
                )
                .exclude(pk__in=used_ids)
                .order_by('exchange_date', 'pk')
                .first()
            )
            if transfer is None:
                continue
            row.transfer = transfer
            row.decision = BankStatementRow.Decision.TRANSFERRED
            row.decided_at = timezone.now()
            row.save(update_fields=['transfer', 'decision', 'decided_at'])
            BankStatementDecisionAudit.objects.create(
                row=row,
                actor_id=account.user_id,
                decision=row.decision,
            )
            used_ids.add(transfer.pk)
            settled_upload_ids.add(row.upload_id)
            settled += 1
        for upload in BankStatementUpload.objects.filter(
            pk__in=settled_upload_ids,
        ):
            self.refresh_outcome_counts(upload)
        return settled
