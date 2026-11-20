"""ORM access for statement rows closed by a transfer or a transaction."""

from collections.abc import Sequence
from datetime import datetime
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
from hasta_la_vista_money.core.calendar_days import movement_calendar_date
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
    mirroring_transfer_q,
)

_REPAYMENT_ROW = Q(
    upload__account__type_account__in=constants.CREDIT_ACCOUNT_TYPES,
    transaction_type=BankStatementRow.TransactionType.INCOME,
)


class StatementRowRepository:
    """Statement rows linked to movements and repayment rows."""

    @staticmethod
    def bank_data_available_q(
        now: datetime | None = None,
        prefix: str = '',
    ) -> Q:
        """Return the row filter for still-stored bank details.

        An explicit row deadline wins over the upload-level fallback, so a
        row restored by a re-upload is available after the original cleanup.
        """
        moment = now or timezone.now()
        return Q(**{f'{prefix}data_cleaned_at__isnull': True}) & (
            Q(**{f'{prefix}data_expires_at__gt': moment})
            | Q(
                **{
                    f'{prefix}data_expires_at__isnull': True,
                    f'{prefix}upload__expires_at__gt': moment,
                    f'{prefix}upload__retention_cleaned_at__isnull': True,
                },
            )
        )

    @staticmethod
    def bank_data_due_q(
        now: datetime | None = None,
        prefix: str = '',
    ) -> Q:
        """Return the row filter for bank details due for cleanup."""
        moment = now or timezone.now()
        return Q(**{f'{prefix}data_cleaned_at__isnull': True}) & (
            Q(**{f'{prefix}data_expires_at__lte': moment})
            | Q(
                **{
                    f'{prefix}data_expires_at__isnull': True,
                    f'{prefix}upload__expires_at__lte': moment,
                    f'{prefix}upload__retention_cleaned_at__isnull': True,
                },
            )
        )

    @staticmethod
    def stamp_legacy_cleaned_rows(
        upload_id: int,
        marker: datetime,
    ) -> int:
        """Keep legacy rows cleaned before an upload marker is reset.

        Rows without their own deadline were only unavailable because the
        upload generation was cleaned. Stamp that old marker on them under
        row locks first, so a renewed generation cannot make their empty
        details look available. A later restore clears the marker only for
        rows the new parse actually matches.
        """
        row_ids = list(
            BankStatementRow.objects.select_for_update()
            .filter(
                upload_id=upload_id,
                data_cleaned_at__isnull=True,
                data_expires_at__isnull=True,
            )
            .values_list('pk', flat=True),
        )
        if not row_ids:
            return 0
        return BankStatementRow.objects.filter(pk__in=row_ids).update(
            data_cleaned_at=marker,
        )

    @staticmethod
    def locked_rows_by_position(
        upload_id: int,
    ) -> dict[int, BankStatementRow]:
        """Lock and index one upload's rows by their stable position."""
        rows = BankStatementRow.objects.select_for_update().filter(
            upload_id=upload_id,
            source_row_position__isnull=False,
        )
        return {
            row.source_row_position: row
            for row in rows
            if row.source_row_position is not None
        }

    @staticmethod
    def same_file_posted_transactions(
        upload: BankStatementUpload,
        positions: set[int],
    ) -> dict[int, list[Transaction]]:
        """Movements that this exact file position already produced.

        Only the stored file hash plus the stable position proves the link;
        a date or amount similarity is never used here.
        """
        if not upload.file_hash or not positions:
            return {}
        movements = Transaction.objects.filter(
            account_id=upload.account_id,
            source_file_hash=upload.file_hash,
            source_row_position__in=positions,
        ).order_by('pk')
        posted: dict[int, list[Transaction]] = {}
        for movement in movements:
            if movement.source_row_position is None:
                continue
            posted.setdefault(movement.source_row_position, []).append(
                movement,
            )
        return posted

    @staticmethod
    def trusted_movement_for_hash(
        account_id: int,
        source_ref_hash: str,
        key_id: str,
        version: int,
    ) -> Transaction | None:
        """Return the single movement owning this exact trusted fingerprint."""
        movements = list(
            Transaction.objects.filter(
                account_id=account_id,
                source_ref_hash=source_ref_hash,
                source_ref_key_id=key_id,
                source_ref_version=version,
                source_identity_trusted=True,
            ).order_by('pk')[:2],
        )
        return movements[0] if len(movements) == 1 else None

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
        reopened: dict[str, object] = {
            'transaction': None,
            'transfer': None,
            'decided_at': None,
        }
        if isinstance(movement, Transaction) and movement.category_id:
            # The owner already confirmed this category; keep it for the
            # reopened row instead of guessing a blank one.
            reopened['suggested_category'] = str(movement.category.name)[
                : constants.TWO_HUNDRED_FIFTY
            ]
        rows.filter(_REPAYMENT_ROW).update(
            decision=BankStatementRow.Decision.NEEDS_TRANSFER,
            **reopened,
        )
        rows.exclude(_REPAYMENT_ROW).update(
            decision=BankStatementRow.Decision.PENDING,
            **reopened,
        )
        return uploads

    def get_available_owned_row(
        self,
        row_id: int,
        user_id: int,
    ) -> BankStatementRow | None:
        """Return an owned, still-readable repayment row for display."""
        return (
            BankStatementRow.objects.filter(
                self.bank_data_available_q(),
                pk=row_id,
                upload__user_id=user_id,
                upload__account__user_id=user_id,
                decision=BankStatementRow.Decision.NEEDS_TRANSFER,
            )
            .select_related('upload__account')
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

        A transfer decision locks the counterparty account before this call,
        so here the account lock is already held by the same transaction;
        the remaining order upload then row stays unchanged.
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

    def get_owned_row_context(
        self,
        row_id: int,
        user_id: int,
    ) -> BankStatementRow | None:
        """Read one owned row with upload and account, without locking.

        Transfer decisions use this to resolve the counterparty pair before
        taking locks. The returned values are re-read under locks and never
        trusted for the decision itself.
        """
        return (
            BankStatementRow.objects.filter(
                pk=row_id,
                upload__user_id=user_id,
                upload__account__user_id=user_id,
            )
            .select_related('upload__account', 'upload__user')
            .first()
        )

    def lock_duplicate_root(
        self,
        row: BankStatementRow,
    ) -> BankStatementRow | None:
        """Lock and return the original row of a duplicate presentation.

        The account is already locked by the caller, so following the chain
        to its root is stable. A cycle or a self-reference is invalid and
        yields no link target; the caller must then fail closed.
        """
        if row.duplicate_of_id is None:
            return None
        seen: set[int] = set()
        current = row.duplicate_of_id
        while True:
            if current == row.pk or current in seen:
                return None
            seen.add(current)
            root = (
                BankStatementRow.objects.select_for_update()
                .select_related('upload')
                .get(pk=current)
            )
            if root.duplicate_of_id is None:
                return root
            current = root.duplicate_of_id

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
                row_date=movement_calendar_date(
                    row.transaction_date,
                    row.bank_calendar_date,
                ),
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
