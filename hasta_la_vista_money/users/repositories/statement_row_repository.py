"""ORM access for statement rows closed by a transfer or a transaction."""

from collections.abc import Sequence
from functools import reduce
from operator import or_

from django.db.models import Exists, OuterRef, Q, QuerySet
from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.transactions.models import Transaction
from hasta_la_vista_money.users.models import (
    BankStatementDecisionAudit,
    BankStatementRow,
    BankStatementUpload,
)
from hasta_la_vista_money.users.services.statement_transfer_matching import (
    TRANSFER_DATE_WINDOW,
    local_row_date,
)

_REPAYMENT_ROW = Q(
    upload__account__type_account__in=constants.CREDIT_ACCOUNT_TYPES,
    transaction_type=BankStatementRow.TransactionType.INCOME,
)


class StatementRowRepository:
    """Statement rows linked to movements and repayment rows."""

    @staticmethod
    def _linked_rows(
        movement: Transaction | TransferMoneyLog,
    ) -> QuerySet[BankStatementRow]:
        if isinstance(movement, TransferMoneyLog):
            return BankStatementRow.objects.filter(transfer=movement)
        return BankStatementRow.objects.filter(transaction=movement)

    def has_linked_row(self, movement: Transaction | TransferMoneyLog) -> bool:
        return self._linked_rows(movement).exists()

    def release_linked_rows(
        self,
        movement: Transaction | TransferMoneyLog,
    ) -> list[BankStatementUpload]:
        """Reopen the movement's rows and return their uploads.

        A credit-account repayment goes back to waiting for a transfer,
        every other row goes back to the pending decision.
        """
        rows = self._linked_rows(movement)
        uploads = list(
            BankStatementUpload.objects.filter(
                pk__in=rows.values('upload_id'),
            ),
        )
        reopened = {'transaction': None, 'transfer': None, 'decided_at': None}
        rows.filter(_REPAYMENT_ROW).update(
            decision=BankStatementRow.Decision.NEEDS_TRANSFER,
            **reopened,
        )
        rows.exclude(_REPAYMENT_ROW).update(
            decision=BankStatementRow.Decision.PENDING,
            **reopened,
        )
        return uploads

    def lock_account_row(
        self,
        row_id: int,
        account: Account,
    ) -> BankStatementRow | None:
        return (
            BankStatementRow.objects.select_for_update()
            .select_related('upload')
            .filter(
                pk=row_id,
                upload__user_id=account.user_id,
                upload__account=account,
            )
            .first()
        )

    def lock_owned_row(self, row_id: int, user_id: int) -> BankStatementRow:
        """Raises ``BankStatementRow.DoesNotExist`` for a foreign row."""
        return (
            BankStatementRow.objects.select_for_update()
            .select_related('upload__account', 'upload__user')
            .get(
                pk=row_id,
                upload__user_id=user_id,
                upload__account__user_id=user_id,
            )
        )

    def lock_owned_transfer(
        self,
        transfer_id: int,
        user_id: int,
    ) -> TransferMoneyLog | None:
        return (
            TransferMoneyLog.objects.select_for_update()
            .filter(pk=transfer_id, user_id=user_id)
            .first()
        )

    def transfers_into_rows(
        self,
        rows: Sequence[BankStatementRow],
    ) -> list[TransferMoneyLog]:
        """Transfers that may have paid any of the repayment rows, one query.

        Same rule as ``find_mirroring_transfers``: into the row's account,
        the same amount, within the date window, not bound to another row
        of that account. Rows without amount or date match nothing.
        """
        matches = [
            Q(
                user_id=row.upload.user_id,
                to_account_id=row.upload.account_id,
                amount=row.amount,
                exchange_date__date__gte=(
                    local_row_date(row.transaction_date) - TRANSFER_DATE_WINDOW
                ),
                exchange_date__date__lte=(
                    local_row_date(row.transaction_date) + TRANSFER_DATE_WINDOW
                ),
            )
            for row in rows
            if row.amount is not None and row.transaction_date is not None
        ]
        if not matches:
            return []
        occupied = BankStatementRow.objects.filter(
            transfer_id=OuterRef('pk'),
            upload__account_id=OuterRef('to_account_id'),
        )
        return list(
            TransferMoneyLog.objects.filter(reduce(or_, matches))
            .exclude(Exists(occupied))
            .select_related('from_account')
            .order_by('exchange_date', 'pk'),
        )

    def close_row(
        self,
        row: BankStatementRow,
        transfer: TransferMoneyLog,
    ) -> None:
        row.transfer = transfer
        row.decision = BankStatementRow.Decision.TRANSFERRED
        row.decided_at = timezone.now()
        row.save(update_fields=['transfer', 'decision', 'decided_at'])
        BankStatementDecisionAudit.objects.create(
            row=row,
            actor_id=transfer.user_id,
            decision=row.decision,
        )
