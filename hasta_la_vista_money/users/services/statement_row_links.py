"""Statement rows closed by a movement, and credit-card repayment rows."""

from collections.abc import Sequence
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
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
    StaleStatementCandidateError,
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
        self.statement_row_repository.close_row(row, transfer)
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
