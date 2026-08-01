from decimal import Decimal

from django.db import transaction
from django.db.models import Count, QuerySet
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import Category, Transaction
from hasta_la_vista_money.users.models import (
    BankStatementCandidate,
    BankStatementRow,
    BankStatementUpload,
)


class InvalidReconciliationDecisionError(ValueError):
    """Raised when a statement row decision is unsupported."""


class ReconciliationDecisionConflictError(ValueError):
    """Raised when a decided row receives a different decision."""


class StaleStatementCandidateError(ValueError):
    """Raised when a selected candidate is no longer current."""


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
        row = (
            BankStatementRow.objects.select_for_update()
            .select_related('upload', 'upload__account')
            .get(
                pk=row_id,
                upload__user_id=user_id,
                upload__account__user_id=user_id,
            )
        )
        if row.decision != BankStatementRow.Decision.PENDING:
            if row.decision != decision:
                raise ReconciliationDecisionConflictError(decision)
            if decision == BankStatementRow.Decision.LINKED:
                candidate = self._validated_candidate(row, candidate_id)
                if row.transaction_id != candidate.pk:
                    raise ReconciliationDecisionConflictError(candidate_id)
            return row

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
        self.refresh_outcome_counts(row.upload)
        if not BankStatementRow.objects.filter(
            upload=row.upload,
            decision=BankStatementRow.Decision.PENDING,
        ).exists():
            row.upload.status = BankStatementUpload.Status.COMPLETED
            row.upload.save(update_fields=['status'])
        return row

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
        upload.imported_count = (
            upload.income_count
            + upload.expense_count
            + counts.get(BankStatementRow.Decision.NEW, 0)
        )
        upload.save(
            update_fields=[
                'linked_count',
                'awaiting_decision_count',
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
        date_matches = candidate.date == row.transaction_date
        if row.match_calendar_date:
            date_matches = (
                timezone.localtime(candidate.date).date()
                == timezone.localtime(row.transaction_date).date()
            )
        return bool(
            candidate.account_id == row.upload.account_id
            and candidate.user_id == row.upload.user_id
            and candidate.type == row.transaction_type
            and candidate.amount == row.amount
            and date_matches,
        )

    def current_candidates(
        self,
        row: BankStatementRow,
    ):
        candidates = Transaction.objects.filter(
            account=row.upload.account,
            user=row.upload.user,
            type=row.transaction_type,
            amount=row.amount,
        )
        if row.match_calendar_date:
            return candidates.filter(
                date__date=timezone.localtime(row.transaction_date).date(),
            ).order_by('date', 'pk')
        return candidates.filter(date=row.transaction_date).order_by(
            'date',
            'pk',
        )

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
            description=row.description,
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
