from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from django.db import DatabaseError, transaction
from django.db.models import Count, QuerySet
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import Category, Transaction
from hasta_la_vista_money.users.models import (
    BankStatementCandidate,
    BankStatementDecisionAudit,
    BankStatementRow,
    BankStatementUpload,
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
            .prefetch_related('candidates__transaction__category')
            .order_by('transaction_date', 'pk')
        )

    @transaction.atomic
    def decide(
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
                candidate = self._validated_candidate(row, candidate_id)
                if row.transaction_id != candidate.pk:
                    raise ReconciliationDecisionConflictError(candidate_id)
            return row
        if timezone.now() >= row.upload.expires_at:
            raise ReconciliationExpiredError(row_id)

        if decision == BankStatementRow.Decision.LINKED:
            row.transaction = self._validated_candidate(row, candidate_id)
        elif decision == BankStatementRow.Decision.NEW:
            row.transaction = self._create_transaction(row)
        else:
            raise InvalidReconciliationDecisionError(decision)

        row.decision = decision
        row.decided_at = timezone.now()
        row.save(
            update_fields=['transaction', 'decision', 'decided_at'],
        )
        BankStatementDecisionAudit.objects.create(
            row=row,
            actor_id=user_id,
            decision=decision,
            transaction=row.transaction,
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
        row.transaction = self._create_transaction(row)
        row.decision = BankStatementRow.Decision.NEW
        row.decided_at = timezone.now()
        row.save(update_fields=['transaction', 'decision', 'decided_at'])
        BankStatementDecisionAudit.objects.create(
            row=row,
            actor_id=user_id,
            decision=row.decision,
            previous_transaction=previous_transaction,
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
        """Apply a decision independently to each selected statement row."""
        results = []
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
                    self.decide(row_id, decision, user_id)
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
            for candidate in row.candidates.select_related('transaction')
            if candidate.transaction is not None
            and self._candidate_is_current(row, candidate.transaction)
        ]
        if len(candidate_ids) > 1:
            raise AmbiguousStatementCandidateError(row_id)
        if not candidate_ids:
            raise StaleStatementCandidateError(row_id)
        return self.decide(
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
                'expired_count',
                'imported_count',
            ],
        )

    def _validated_candidate(
        self,
        row: BankStatementRow,
        candidate_id: int | None,
    ) -> Transaction:
        if candidate_id is None:
            raise InvalidReconciliationDecisionError('candidate')
        candidate = (
            BankStatementCandidate.objects.filter(
                pk=candidate_id,
                row=row,
            )
            .select_related('transaction')
            .first()
        )
        if (
            candidate is None
            or candidate.transaction is None
            or not self._candidate_is_current(
                row,
                candidate.transaction,
            )
        ):
            raise StaleStatementCandidateError(candidate_id)
        return candidate.transaction

    def _candidate_is_current(
        self,
        row: BankStatementRow,
        candidate: Transaction,
    ) -> bool:
        transaction_type = row.transaction_type
        amount = row.amount
        transaction_date = row.transaction_date
        if (
            transaction_type is None
            or amount is None
            or transaction_date is None
        ):
            return False
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

    def current_candidates(
        self,
        row: BankStatementRow,
    ) -> QuerySet[Transaction]:
        transaction_type = row.transaction_type
        amount = row.amount
        transaction_date = row.transaction_date
        if (
            transaction_type is None
            or amount is None
            or transaction_date is None
        ):
            return Transaction.objects.none()
        candidates = Transaction.objects.filter(
            account=row.upload.account,
            user=row.upload.user,
            type=transaction_type,
            amount=amount,
        )
        if row.match_calendar_date:
            return candidates.filter(
                date__date=timezone.localtime(transaction_date).date(),
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
