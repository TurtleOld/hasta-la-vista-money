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

    def lock_owned_upload_and_row(
        self,
        row_id: int,
        user_id: int,
    ) -> tuple[BankStatementUpload, BankStatementRow]:
        """Lock account, upload and row in the agreed decision order.

        The upload and account are resolved without a lock first so the
        ``FOR UPDATE`` queries lock plain rows: a nullable join cannot be
        locked. Raises ``BankStatementRow.DoesNotExist`` for a foreign row.
        """
        owner = (
            BankStatementRow.objects.filter(
                pk=row_id,
                upload__user_id=user_id,
                upload__account__user_id=user_id,
            )
            .values_list('upload_id', 'upload__account_id')
            .first()
        )
        if owner is None:
            raise BankStatementRow.DoesNotExist
        upload_id, account_id = owner
        account = Account.objects.select_for_update().get(pk=account_id)
        upload = BankStatementUpload.objects.select_for_update().get(
            pk=upload_id,
            user_id=user_id,
        )
        upload.account = account
        row = BankStatementRow.objects.select_for_update().get(
            pk=row_id,
            upload=upload,
        )
        row.upload = upload
        return upload, row

    def suspend_row(
        self,
        row: BankStatementRow,
        decision: str,
        resume_decision: str,
        reason: str,
        actor_id: int,
    ) -> None:
        """Write one suspension decision with its audit entry.

        Callers own the locks and the state guards; this keeps the defer
        transition identical for markup and reconciliation paths.
        """
        row.decision = decision
        row.resume_decision = resume_decision
        row.decision_reason = reason
        row.decided_at = timezone.now()
        row.save(
            update_fields=[
                'decision',
                'resume_decision',
                'decision_reason',
                'decided_at',
            ],
        )
        self.record_decision(row, actor_id, reason)

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

    def record_decision(
        self,
        row: BankStatementRow,
        actor_id: int,
        reason: str = '',
    ) -> None:
        BankStatementDecisionAudit.objects.create(
            row=row,
            actor_id=actor_id,
            decision=row.decision,
            reason=reason,
        )
