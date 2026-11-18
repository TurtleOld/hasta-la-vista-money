"""Statement rows closed by a movement, and credit-card repayment rows."""

from collections.abc import Sequence
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
from hasta_la_vista_money.users.models import BankStatementRow
from hasta_la_vista_money.users.protocols.services import (
    BankStatementReconciliationServiceProtocol,
)
from hasta_la_vista_money.users.repositories.statement_row_repository import (
    StatementRowRepository,
)
from hasta_la_vista_money.users.services.bank_statement_reconciliation import (
    ReconciliationDecisionConflictError,
    ReconciliationExpiredError,
    StaleStatementCandidateError,
)
from hasta_la_vista_money.users.services.statement_retention_policy import (
    row_has_bank_data,
)

_SUSPENDABLE_DECISIONS = frozenset(
    {
        BankStatementRow.Decision.AWAITING_MARKUP,
        BankStatementRow.Decision.PENDING,
        BankStatementRow.Decision.NEEDS_TRANSFER,
    },
)


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
    ) -> None:
        """Reopen rows closed by the movement and recount their uploads."""
        for upload in self.statement_row_repository.release_linked_rows(
            movement,
        ):
            self.reconciliation_service.refresh_outcome_counts(upload)

    def lock_repayment_row(
        self,
        row_id: int,
        *,
        user_id: int,
        to_account: Account,
        amount: Decimal,
    ) -> BankStatementRow:
        """Lock the open repayment row that a transfer is about to close."""
        try:
            upload, row = (
                self.statement_row_repository.lock_owned_upload_and_row(
                    row_id,
                    user_id,
                )
            )
        except BankStatementRow.DoesNotExist as error:
            raise ValidationError(
                _('Строка выписки не относится к счёту получателя.'),
            ) from error
        if upload.account_id != to_account.pk:
            raise ValidationError(
                _('Строка выписки не относится к счёту получателя.'),
            )
        if row.decision != BankStatementRow.Decision.NEEDS_TRANSFER:
            raise ValidationError(_('Строка выписки уже закрыта.'))
        if not row_has_bank_data(row):
            raise ValidationError(
                _(
                    'Срок хранения строки выписки истёк. '
                    'Загрузите выписку повторно.',
                ),
            )
        if row.duplicate_of_id is not None:
            root = self.statement_row_repository.lock_duplicate_root(row)
            if root is not None and root.upload.account_id != upload.account_id:
                raise ValidationError(
                    _('Строка выписки не относится к счёту получателя.'),
                )
            raise ValidationError(
                _(
                    'Это повторное представление уже сохранённой операции. '
                    'Решение принимается по исходной строке.',
                ),
            )
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
        self.statement_row_repository.close_row(row, transfer)
        self.statement_row_repository.record_decision(row, transfer.user_id)
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
            _upload, row = (
                self.statement_row_repository.lock_owned_upload_and_row(
                    row_id,
                    user_id,
                )
            )
            if row.decision != BankStatementRow.Decision.NEEDS_TRANSFER:
                raise ReconciliationDecisionConflictError(row.decision)
            if not row_has_bank_data(row):
                raise ReconciliationExpiredError(row.pk)
            if row.duplicate_of_id is not None:
                raise ReconciliationDecisionConflictError('duplicate')
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

    def defer(self, row_id: int, user_id: int) -> BankStatementRow:
        """Leave the row unresolved without touching money."""
        return self._suspend(
            row_id,
            user_id,
            BankStatementRow.Decision.DEFERRED,
        )

    def exclude(
        self,
        row_id: int,
        user_id: int,
        reason: str,
    ) -> BankStatementRow:
        """Close the row as consciously left out, with the owner's reason."""
        cleaned = (reason or '').strip()
        if not cleaned:
            raise ValidationError(
                _('Укажите причину исключения строки.'),
            )
        return self._suspend(
            row_id,
            user_id,
            BankStatementRow.Decision.EXCLUDED,
            reason=cleaned,
        )

    def resume(self, row_id: int, user_id: int) -> BankStatementRow:
        """Return a suspended row to the mechanism it came from.

        A repeated resume is idempotent only when the last decision audit
        proves that this row was already resumed to its current decision.
        """
        with (
            audit_operation(
                kind=AuditOperationKind.STATEMENT_IMPORT_RESOLUTION,
            ),
            transaction.atomic(),
        ):
            upload, row = (
                self.statement_row_repository.lock_owned_upload_and_row(
                    row_id,
                    user_id,
                )
            )
            if row.decision not in {
                BankStatementRow.Decision.DEFERRED,
                BankStatementRow.Decision.EXCLUDED,
            }:
                if self._resume_already_applied(row):
                    return row
                self._assert_data_available(row)
                raise ReconciliationDecisionConflictError(row.decision)
            if row.transaction_id or row.transfer_id:
                # A suspended row never owns a movement; return it only by
                # the audited decision that detached it first.
                raise ReconciliationDecisionConflictError('linked')
            target = row.resume_decision
            if target not in _SUSPENDABLE_DECISIONS:
                raise ReconciliationDecisionConflictError(row.decision)
            self._assert_data_available(row)
            row.decision = target
            row.decision_reason = ''
            row.decided_at = timezone.now()
            row.save(
                update_fields=[
                    'decision',
                    'decision_reason',
                    'decided_at',
                ],
            )
            self.statement_row_repository.record_decision(row, user_id)
            self.reconciliation_service.refresh_outcome_counts(upload)
            return row

    @staticmethod
    def _resume_already_applied(row: BankStatementRow) -> bool:
        """Tell a repeated resume from an arbitrary decision on a row.

        ``resume_decision`` is kept after a resume as the proof that the
        row was suspended; the last audit entry must also carry the same
        decision. An unrelated decision that merely left the row PENDING
        has no suspension proof and is rejected.
        """
        if row.decision not in _SUSPENDABLE_DECISIONS:
            return False
        if row.resume_decision != row.decision:
            return False
        last = (
            row.decision_audits.order_by('-created_at', '-pk')
            .values_list('decision', flat=True)
            .first()
        )
        return last == row.decision

    @transaction.atomic
    def _suspend(
        self,
        row_id: int,
        user_id: int,
        decision: str,
        reason: str = '',
    ) -> BankStatementRow:
        with audit_operation(
            kind=AuditOperationKind.STATEMENT_IMPORT_RESOLUTION,
        ):
            upload, row = (
                self.statement_row_repository.lock_owned_upload_and_row(
                    row_id,
                    user_id,
                )
            )
            if row.decision == decision:
                return row
            if row.decision not in _SUSPENDABLE_DECISIONS:
                raise ReconciliationDecisionConflictError(row.decision)
            self._assert_data_available(row)
            if row.transaction_id or row.transfer_id:
                raise ReconciliationDecisionConflictError('linked')
            self.statement_row_repository.suspend_row(
                row,
                decision,
                row.decision,
                reason,
                user_id,
            )
            self.reconciliation_service.refresh_outcome_counts(upload)
            return row

    @staticmethod
    def _assert_data_available(row: BankStatementRow) -> None:
        """Reject decisions on a row whose bank details were removed."""
        if not row_has_bank_data(row):
            raise ReconciliationExpiredError(row.pk)
