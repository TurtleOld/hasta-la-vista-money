"""ORM access for statement rows closed by a transfer or a transaction."""

from collections.abc import Sequence
from functools import reduce
from operator import or_

from django.db.models import (
    BooleanField,
    Exists,
    ExpressionWrapper,
    OuterRef,
    Q,
    QuerySet,
)
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
from hasta_la_vista_money.users.repositories.transfer_matching import (
    local_row_date,
    mirroring_transfer_q,
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

    def repayment_candidates(
        self,
        rows: Sequence[BankStatementRow],
    ) -> dict[int, list[TransferMoneyLog]]:
        """Transfers that may have paid each repayment row, one query.

        Rule of ``mirroring_transfer_q``, not bound to another row of that
        account. Rows without amount or date match nothing.
        """
        rules = {
            f'pays_row_{row.pk}': mirroring_transfer_q(
                account_id=row.upload.account_id,
                user_id=row.upload.user_id,
                transaction_type=BankStatementRow.TransactionType.INCOME,
                amount=row.amount,
                row_date=local_row_date(row.transaction_date),
            )
            for row in rows
            if row.amount is not None and row.transaction_date is not None
        }
        candidates: dict[int, list[TransferMoneyLog]] = {
            row.pk: [] for row in rows
        }
        if not rules:
            return candidates
        occupied = BankStatementRow.objects.filter(
            transfer_id=OuterRef('pk'),
            upload__account_id=OuterRef('to_account_id'),
        )
        transfers = (
            TransferMoneyLog.objects.filter(reduce(or_, rules.values()))
            .exclude(Exists(occupied))
            .annotate(
                **{
                    name: ExpressionWrapper(rule, output_field=BooleanField())
                    for name, rule in rules.items()
                },
            )
            .select_related('from_account')
            .order_by('exchange_date', 'pk')
        )
        for transfer in transfers:
            for row_pk, paid_by in candidates.items():
                if getattr(transfer, f'pays_row_{row_pk}', False):
                    paid_by.append(transfer)
        return candidates

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
