"""Statement rows closed by a movement, and credit-card repayment rows."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.system.models import AuditOperationKind
from hasta_la_vista_money.system.services.audit_context import audit_operation
from hasta_la_vista_money.transactions.models import Transaction
from hasta_la_vista_money.users.models import (
    BankStatementDecisionAudit,
    BankStatementRow,
    BankStatementUpload,
)
from hasta_la_vista_money.users.protocols.services import (
    BankStatementReconciliationServiceProtocol,
)
from hasta_la_vista_money.users.repositories.statement_row_repository import (
    LockedStatementRow,
    StatementRowRepository,
)
from hasta_la_vista_money.users.services.bank_statement_reconciliation import (
    ReconciliationDecisionConflictError,
    StaleStatementCandidateError,
)
from hasta_la_vista_money.users.services.bank_statement_retention import (
    CREATED_DECISIONS,
    scrub_movement_audit_copy,
)


def _released_decision(
    row: LockedStatementRow,
    repayment_ids: set[int],
) -> str:
    """Choose the decision a released row returns to."""
    if row.retention_cleaned_at is not None:
        return BankStatementRow.Decision.EXPIRED
    if row.pk in repayment_ids:
        return BankStatementRow.Decision.NEEDS_TRANSFER
    return BankStatementRow.Decision.PENDING


class StatementRowLinkService:
    """Keep statement rows consistent with the movements that close them."""

    def __init__(
        self,
        statement_row_repository: StatementRowRepository,
        reconciliation_service: BankStatementReconciliationServiceProtocol,
    ) -> None:
        self.statement_row_repository = statement_row_repository
        self.reconciliation_service = reconciliation_service

    def has_linked_row(self, movement: Transaction | TransferMoneyLog) -> bool:
        """Return whether a statement row is closed by this movement."""
        return self.statement_row_repository.has_linked_row(movement)

    def release_linked_rows(
        self,
        movement: Transaction | TransferMoneyLog,
    ) -> bool:
        """Release rows closed by the movement and recount their uploads.

        A cleaned upload kept no bank payload, so its rows become
        ``EXPIRED`` instead of an unresolvable pending decision and the
        upload stays completed with unresolved rows. A credit-account
        repayment goes back to waiting for a transfer, every other row
        goes back to the pending decision. Rows that are exact repeat
        observations of a released row are released too, so a closed row
        never outlives its movement.

        Returns whether the movement was created from a cleaned upload;
        only such a movement proves its deletion audit copy is a bank copy.
        A movement merely linked as ``LINKED`` keeps its own audit.
        """
        locked = self.statement_row_repository.lock_released_rows(movement)
        if not locked.linked:
            return False
        scrub_audit = any(
            row.retention_cleaned_at is not None
            and row.decision in CREATED_DECISIONS
            for row in locked.linked
        )
        rows = (*locked.linked, *locked.repeats)
        released = [
            (
                row.pk,
                row.decision,
                _released_decision(row, locked.repayment_ids),
            )
            for row in locked.linked
        ]
        released += [
            (
                row.pk,
                row.decision,
                _released_decision(row, set()),
            )
            for row in locked.repeats
        ]
        expired_ids = [
            pk
            for pk, _, decision in released
            if decision == BankStatementRow.Decision.EXPIRED
        ]
        needs_transfer_ids = [
            pk
            for pk, _, decision in released
            if decision == BankStatementRow.Decision.NEEDS_TRANSFER
        ]
        pending_ids = [
            pk
            for pk, _, decision in released
            if decision == BankStatementRow.Decision.PENDING
        ]
        if expired_ids:
            self.statement_row_repository.expire_rows(
                expired_ids,
                timezone.now(),
            )
            cleaned_upload_ids = {
                row.upload_id
                for row in rows
                if row.retention_cleaned_at is not None
            }
            self.statement_row_repository.update_upload_status(
                cleaned_upload_ids,
                BankStatementUpload.Status.COMPLETED_WITH_UNRESOLVED,
            )
        if needs_transfer_ids:
            self.statement_row_repository.reopen_rows(
                needs_transfer_ids,
                BankStatementRow.Decision.NEEDS_TRANSFER,
                clear_canonical=False,
            )
        if pending_ids:
            self.statement_row_repository.reopen_rows(
                pending_ids,
                BankStatementRow.Decision.PENDING,
                clear_canonical=True,
            )
        self.statement_row_repository.record_release_decisions(
            movement,
            released,
        )
        for upload in locked.uploads:
            self.reconciliation_service.refresh_outcome_counts(upload)
        return scrub_audit

    def scrub_deleted_movement_audit(
        self,
        *,
        user_id: int,
        model_name: str,
        object_id: int,
    ) -> None:
        """Scrub bank values from the deletion copy of a cleaned movement."""
        scrub_movement_audit_copy(
            user_id=user_id,
            model_name=model_name,
            object_id=object_id,
        )

    def invalidate_linked_checks(
        self,
        movement: Transaction | TransferMoneyLog,
    ) -> None:
        """Invalidate statement checks affected by a date change."""
        self.statement_row_repository.invalidate_linked_checks(movement)

    def link_duplicate(
        self,
        row_id: int,
        canonical_row_id: int,
        user_id: int,
    ) -> BankStatementRow:
        """Mark a row as an exact repeat of one resolved canonical row.

        Raises:
            ReconciliationDecisionConflictError: The row or the canonical
                row is already resolved, or the canonical row is itself a
                duplicate — a chain or cycle is never closed automatically.
        """
        with (
            audit_operation(
                kind=AuditOperationKind.STATEMENT_IMPORT_RESOLUTION,
            ),
            transaction.atomic(),
        ):
            row = self.statement_row_repository.lock_owned_row(
                row_id,
                user_id,
            )
            canonical = self.statement_row_repository.lock_owned_row(
                canonical_row_id,
                user_id,
            )
            if row.pk == canonical.pk:
                raise ReconciliationDecisionConflictError('self')
            if row.decision != BankStatementRow.Decision.PENDING:
                raise ReconciliationDecisionConflictError(row.decision)
            self._validate_canonical_duplicate(row, canonical)
            row.decision = BankStatementRow.Decision.DUPLICATE
            row.canonical_row = canonical
            row.decided_at = timezone.now()
            row.save(
                update_fields=['decision', 'canonical_row', 'decided_at'],
            )
            BankStatementDecisionAudit.objects.create(
                row=row,
                actor_id=user_id,
                decision=row.decision,
                previous_decision=BankStatementRow.Decision.PENDING,
            )
            self.reconciliation_service.refresh_outcome_counts(row.upload)
            return row

    @classmethod
    def _validate_canonical_duplicate(
        cls,
        row: BankStatementRow,
        canonical: BankStatementRow,
    ) -> None:
        """Allow only a resolved, proven canonical row of the same account."""
        cls._validate_canonical_decision(canonical)
        if canonical.upload.account_id != row.upload.account_id:
            raise ReconciliationDecisionConflictError('account')
        if (
            canonical.transaction_type != row.transaction_type
            or canonical.amount != row.amount
            or canonical.transaction_date is None
            or row.transaction_date is None
            or not cls._same_bank_date(row, canonical)
        ):
            raise ReconciliationDecisionConflictError('observation')
        cls._validate_canonical_movement(row, canonical)

    @staticmethod
    def _validate_canonical_decision(canonical: BankStatementRow) -> None:
        proven = {
            BankStatementRow.Decision.NEW,
            BankStatementRow.Decision.LINKED,
            BankStatementRow.Decision.TRANSFERRED,
            BankStatementRow.Decision.NOT_A_PAYMENT,
        }
        if canonical.decision == BankStatementRow.Decision.SKIPPED:
            if canonical.exclusion_code not in (
                BankStatementRow.ExclusionCode.values
            ):
                raise ReconciliationDecisionConflictError('skipped')
            return
        if canonical.decision not in proven:
            raise ReconciliationDecisionConflictError(canonical.decision)

    @classmethod
    def _validate_canonical_movement(
        cls,
        row: BankStatementRow,
        canonical: BankStatementRow,
    ) -> None:
        movement = canonical.transaction
        transfer = canonical.transfer
        if canonical.decision in {
            BankStatementRow.Decision.NEW,
            BankStatementRow.Decision.LINKED,
        }:
            if (
                movement is None
                or movement.account_id != row.upload.account_id
                or movement.type != canonical.transaction_type
                or movement.amount != canonical.amount
                or not cls._movement_date_matches(
                    canonical,
                    movement.date,
                )
            ):
                raise ReconciliationDecisionConflictError('movement')
            return
        if canonical.decision == BankStatementRow.Decision.TRANSFERRED:
            if transfer is None or (
                row.upload.account_id
                not in {transfer.from_account_id, transfer.to_account_id}
            ):
                raise ReconciliationDecisionConflictError('transfer')
            if transfer.amount != canonical.amount:
                raise ReconciliationDecisionConflictError('transfer')
            return
        if movement is not None or transfer is not None:
            raise ReconciliationDecisionConflictError('movement')

    @staticmethod
    def _same_bank_date(
        row: BankStatementRow,
        canonical: BankStatementRow,
    ) -> bool:
        if row.transaction_date is None or canonical.transaction_date is None:
            return False
        if row.match_calendar_date or canonical.match_calendar_date:
            return (
                timezone.localtime(row.transaction_date).date()
                == timezone.localtime(canonical.transaction_date).date()
            )
        return row.transaction_date == canonical.transaction_date

    @staticmethod
    def _movement_date_matches(
        canonical: BankStatementRow,
        movement_date: datetime,
    ) -> bool:
        if canonical.transaction_date is None:
            return False
        if canonical.match_calendar_date:
            return (
                timezone.localtime(canonical.transaction_date).date()
                == timezone.localtime(movement_date).date()
            )
        return canonical.transaction_date == movement_date

    def lock_repayment_row(
        self,
        row_id: int,
        *,
        to_account: Account,
        amount: Decimal,
    ) -> BankStatementRow:
        """Lock the open repayment row that a transfer is about to close."""
        row = self.statement_row_repository.lock_account_row(
            row_id,
            to_account,
        )
        if row is None:
            raise ValidationError(
                _('Строка выписки не относится к счёту получателя.'),
            )
        if row.decision != BankStatementRow.Decision.NEEDS_TRANSFER:
            raise ValidationError(_('Строка выписки уже закрыта.'))
        if row.amount != amount:
            raise ValidationError(
                _('Сумма перевода должна совпадать с суммой строки выписки.'),
            )
        return row

    def close_repayment_row(
        self,
        row: BankStatementRow,
        transfer: TransferMoneyLog,
    ) -> None:
        """Close a locked repayment row by the transfer that paid it."""
        previous_decision = row.decision
        self.statement_row_repository.close_row(row, transfer)
        self.statement_row_repository.record_decision(
            row,
            transfer.user_id,
            previous_decision=previous_decision,
        )
        self.reconciliation_service.refresh_outcome_counts(row.upload)

    def repayment_candidates(
        self,
        rows: Sequence[BankStatementRow],
    ) -> dict[int, list[TransferMoneyLog]]:
        """Recorded transfers that may have paid each repayment row."""
        return self.statement_row_repository.repayment_candidates(rows)

    def link_repayment(
        self,
        row_id: int,
        transfer_id: int,
        user_id: int,
    ) -> BankStatementRow:
        """Close a repayment row by a transfer the owner picked.

        Raises ``BankStatementRow.DoesNotExist`` for a foreign row.
        """
        with (
            audit_operation(
                kind=AuditOperationKind.STATEMENT_IMPORT_RESOLUTION,
            ),
            transaction.atomic(),
        ):
            row = self.statement_row_repository.lock_owned_row(
                row_id,
                user_id,
            )
            if row.decision != BankStatementRow.Decision.NEEDS_TRANSFER:
                raise ReconciliationDecisionConflictError(row.decision)
            # The lock keeps two rows of one account from taking one transfer.
            transfer = self.statement_row_repository.lock_owned_transfer(
                transfer_id,
                user_id,
            )
            if (
                transfer is None
                or transfer not in (self.repayment_candidates([row])[row.pk])
            ):
                raise StaleStatementCandidateError(transfer_id)
            self.close_repayment_row(row, transfer)
            return row
