"""ORM access for statement rows closed by a transfer or a transaction."""

from collections.abc import Sequence
from datetime import datetime
from functools import reduce
from operator import or_
from typing import NamedTuple

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


class LockedStatementRow(NamedTuple):
    """One locked statement row and its upload's retention state."""

    pk: int
    decision: str
    upload_id: int
    retention_cleaned_at: datetime | None


class LockedRelease(NamedTuple):
    """Rows and uploads locked to release one deleted movement."""

    linked: list[LockedStatementRow]
    repeats: list[LockedStatementRow]
    repayment_ids: set[int]
    uploads: list[BankStatementUpload]


def _locked_rows(
    rows: QuerySet[BankStatementRow],
) -> list[LockedStatementRow]:
    """Read locked rows without choosing any new decision."""
    return [
        LockedStatementRow(pk, decision, upload_id, cleaned_at)
        for pk, decision, upload_id, cleaned_at in rows.values_list(
            'pk',
            'decision',
            'upload_id',
            'upload__retention_cleaned_at',
        )
    ]


class StatementRowRepository:
    """Statement rows linked to movements and repayment rows."""

    @staticmethod
    def confirmed_exclusions(
        upload_id: int,
    ) -> QuerySet[BankStatementRow]:
        """Return rows of the upload excluded with an approved reason."""
        return (
            BankStatementRow.objects.filter(
                upload_id=upload_id,
                decision=BankStatementRow.Decision.SKIPPED,
                exclusion_code__in=BankStatementRow.ExclusionCode.values,
            )
            .prefetch_related('decision_audits__actor')
            .order_by('transaction_date', 'pk')
        )

    @staticmethod
    def legacy_skipped_rows(
        upload_id: int,
    ) -> QuerySet[BankStatementRow]:
        """Return skipped rows of the upload without an approved reason."""
        return (
            BankStatementRow.objects.filter(
                upload_id=upload_id,
                decision=BankStatementRow.Decision.SKIPPED,
            )
            .exclude(exclusion_code__in=BankStatementRow.ExclusionCode.values)
            .prefetch_related('decision_audits__actor')
            .order_by('transaction_date', 'pk')
        )

    @staticmethod
    def _linked_rows(
        movement: Transaction | TransferMoneyLog,
    ) -> QuerySet[BankStatementRow]:
        if isinstance(movement, TransferMoneyLog):
            return BankStatementRow.objects.filter(transfer=movement)
        return BankStatementRow.objects.filter(transaction=movement)

    def has_linked_row(self, movement: Transaction | TransferMoneyLog) -> bool:
        return self._linked_rows(movement).exists()

    def lock_released_rows(
        self,
        movement: Transaction | TransferMoneyLog,
    ) -> LockedRelease:
        """Lock rows closed by the movement and their repeat observations."""
        rows = self._linked_rows(movement)
        linked = _locked_rows(
            rows.select_for_update().order_by('pk'),
        )
        if not linked:
            return LockedRelease([], [], set(), [])
        repeats = BankStatementRow.objects.filter(
            canonical_row_id__in=[row.pk for row in linked],
        )
        repeat_rows = _locked_rows(
            repeats.select_for_update().order_by('pk'),
        )
        repayment_ids = set(
            rows.filter(_REPAYMENT_ROW).values_list('pk', flat=True),
        )
        uploads = list(
            BankStatementUpload.objects.filter(
                pk__in=rows.values('upload_id'),
            ).union(
                BankStatementUpload.objects.filter(
                    pk__in=repeats.values('upload_id'),
                ),
            ),
        )
        return LockedRelease(linked, repeat_rows, repayment_ids, uploads)

    @staticmethod
    def expire_rows(row_ids: Sequence[int], decided_at: datetime) -> None:
        """Mark locked rows as expired and detach their movement."""
        BankStatementRow.objects.filter(pk__in=row_ids).update(
            decision=BankStatementRow.Decision.EXPIRED,
            transaction=None,
            transfer=None,
            canonical_row=None,
            decided_at=decided_at,
        )

    @staticmethod
    def reopen_rows(
        row_ids: Sequence[int],
        decision: str,
        *,
        clear_canonical: bool,
    ) -> None:
        """Reopen locked rows into the decision chosen by the service."""
        reopened: dict[str, None] = {
            'transaction': None,
            'transfer': None,
            'decided_at': None,
        }
        if clear_canonical:
            reopened['canonical_row'] = None
        BankStatementRow.objects.filter(pk__in=row_ids).update(
            decision=decision,
            **reopened,
        )

    @staticmethod
    def update_upload_status(upload_ids: set[int], status: str) -> None:
        """Persist the status chosen by the service for these uploads."""
        BankStatementUpload.objects.filter(pk__in=upload_ids).update(
            status=status,
        )

    @staticmethod
    def record_release_decisions(
        movement: Transaction | TransferMoneyLog,
        released: Sequence[tuple[int, str, str]],
    ) -> None:
        """Store the decision history of one release in one insert."""
        is_transfer = isinstance(movement, TransferMoneyLog)
        BankStatementDecisionAudit.objects.bulk_create(
            [
                BankStatementDecisionAudit(
                    row_id=pk,
                    actor_id=movement.user_id,
                    previous_decision=previous_decision,
                    decision=decision,
                    previous_transaction_pk=(
                        None if is_transfer else movement.pk
                    ),
                    previous_transfer_pk=(movement.pk if is_transfer else None),
                )
                for pk, previous_decision, decision in released
            ],
        )

    def invalidate_linked_checks(
        self,
        movement: Transaction | TransferMoneyLog,
    ) -> None:
        """Reset affected statement checks and mark them for rechecking."""
        affected = BankStatementUpload.objects.filter(
            pk__in=self._linked_rows(movement).values('upload_id'),
        )
        affected.update(
            account_balance_after=None,
            balance_discrepancy=None,
        )
        affected.filter(balance_is_actual=True).update(
            balance_is_actual=False,
            balance_reason=(
                BankStatementUpload.BalanceReason.MONEY_OR_DATE_CHANGED
            ),
        )

    @staticmethod
    def stored_fingerprint_key_versions(account_id: int) -> set[str]:
        """Return key versions used by fingerprints of one account."""
        row_versions = (
            BankStatementRow.objects.filter(
                upload__account_id=account_id,
            )
            .values_list('source_fingerprint_key_version', flat=True)
            .distinct()
        )
        transaction_versions = (
            Transaction.objects.filter(account_id=account_id)
            .values_list('source_fingerprint_key_version', flat=True)
            .distinct()
        )
        return {
            version
            for version in (*row_versions, *transaction_versions)
            if version
        }

    @staticmethod
    def stored_fingerprint_format_versions(account_id: int) -> set[int]:
        """Return fingerprint format versions used on one account."""
        row_versions = (
            BankStatementRow.objects.filter(
                upload__account_id=account_id,
                source_fingerprint__gt='',
            )
            .values_list('source_fingerprint_format_version', flat=True)
            .distinct()
        )
        transaction_versions = (
            Transaction.objects.filter(
                account_id=account_id,
                source_fingerprint__gt='',
            )
            .values_list('source_fingerprint_format_version', flat=True)
            .distinct()
        )
        return {
            version
            for version in (*row_versions, *transaction_versions)
            if version
        }

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

    def record_decision(
        self,
        row: BankStatementRow,
        actor_id: int,
        *,
        previous_decision: str,
    ) -> None:
        BankStatementDecisionAudit.objects.create(
            row=row,
            actor_id=actor_id,
            decision=row.decision,
            previous_decision=previous_decision,
            transaction_id=row.transaction_id,
            transfer_id=row.transfer_id,
        )
