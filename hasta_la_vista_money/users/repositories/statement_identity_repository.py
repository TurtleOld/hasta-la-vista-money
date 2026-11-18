"""ORM access for bank statement identity fingerprints.

The repository only answers questions about stored fingerprints and the
upload rows that carry them; whether a match is an exact duplicate, a
manual candidate, or a reason to fail closed is decided by
``StatementIdentityService``.
"""

from collections.abc import Iterable, Sequence
from typing import Any

from django.db.models import Q

from hasta_la_vista_money.transactions.models import Transaction
from hasta_la_vista_money.users.models import (
    BankStatementCandidate,
    BankStatementRow,
    BankStatementUpload,
)

_UNRESOLVED_ROW_DECISIONS = (
    BankStatementRow.Decision.PENDING,
    BankStatementRow.Decision.AWAITING_MARKUP,
    BankStatementRow.Decision.NEEDS_TRANSFER,
    BankStatementRow.Decision.DEFERRED,
    BankStatementRow.Decision.PARSE_ERROR,
)

_UNTRUSTED = Q(
    source_ref_hash__isnull=False,
    source_identity_trusted=False,
)
_UNVERIFIED_TRANSACTION = (
    Q(source_ref__isnull=False) | _UNTRUSTED | Q(source_ref_version=0)
)
_UNVERIFIED_ROW = (
    Q(source_ref__isnull=False)
    | _UNTRUSTED
    | Q(source_ref_version=0)
    | (
        Q(source_ref_hash__isnull=True)
        & Q(decision__in=_UNRESOLVED_ROW_DECISIONS)
    )
)


class StatementIdentityRepository:
    """Stored statement fingerprints and their row/movement writers."""

    @staticmethod
    def trusted_movement_exists(
        account_id: int,
        digests: Iterable[str],
        available_key_ids: frozenset[str],
    ) -> bool:
        """Tell whether a readable trusted movement owns one of the digests."""
        wanted = set(digests)
        if not wanted:
            return False
        return Transaction.objects.filter(
            account_id=account_id,
            source_ref_hash__in=wanted,
            source_ref_key_id__in=set(available_key_ids),
            source_ref_version=1,
            source_identity_trusted=True,
        ).exists()

    @staticmethod
    def trusted_presentation_root_id(
        account_id: int,
        digests: Iterable[str],
        available_key_ids: frozenset[str],
        *,
        exclude_upload_id: int | None = None,
    ) -> int | None:
        """Return the root row of a readable trusted duplicate presentation.

        Rows written under another active key still carry the same technical
        identifier; following ``duplicate_of`` finds the original row. A
        cycle or a row outside the account never becomes a link target.
        """
        wanted = set(digests)
        if not wanted:
            return None
        rows = BankStatementRow.objects.filter(
            upload__account_id=account_id,
            source_ref_hash__in=wanted,
            source_ref_key_id__in=set(available_key_ids),
            source_ref_version=1,
            source_identity_trusted=True,
        )
        if exclude_upload_id is not None:
            rows = rows.exclude(upload_id=exclude_upload_id)
        links = dict(rows.values_list('pk', 'duplicate_of_id'))
        if not links:
            return None
        for start in sorted(links):
            seen = {start}
            current = start
            while True:
                parent = links.get(current)
                if parent is None:
                    return current
                if parent in seen:
                    return None
                seen.add(parent)
                current = parent
        return None

    @staticmethod
    def untrusted_transactions(
        account_id: int,
        digests: Iterable[str],
    ) -> list[Transaction]:
        """Return movements whose unverified fingerprint matches a digest."""
        wanted = set(digests)
        if not wanted:
            return []
        return list(
            Transaction.objects.filter(
                _UNTRUSTED,
                account_id=account_id,
                source_ref_hash__in=wanted,
            )
            .select_related('category')
            .order_by('date', 'pk'),
        )

    @staticmethod
    def has_untrusted_identity(account_id: int) -> bool:
        """Tell whether the account keeps unverified bank identity state.

        A nonmatch is not proof of absence while such records exist. Rows
        whose fingerprint could not be written (missing key) still count:
        they are bank-origin unresolved identity, not a manual movement.
        """
        if Transaction.objects.filter(
            _UNVERIFIED_TRANSACTION,
            account_id=account_id,
        ).exists():
            return True
        return BankStatementRow.objects.filter(
            _UNVERIFIED_ROW,
            upload__account_id=account_id,
        ).exists()

    @staticmethod
    def has_unavailable_identity(
        account_id: int,
        available_key_ids: frozenset[str],
    ) -> bool:
        """Tell whether the account depends on a key or version we cannot read.

        Stored fingerprints written by another active key (rolling rotation)
        or by a future format version cannot be reproduced here, so any new
        automatic posting would risk a duplicate.
        """
        unavailable = Q(source_ref_hash__isnull=False) & (
            ~Q(source_ref_key_id__in=set(available_key_ids))
            | ~Q(source_ref_version=1)
        )
        if Transaction.objects.filter(
            unavailable,
            account_id=account_id,
        ).exists():
            return True
        return BankStatementRow.objects.filter(
            unavailable,
            upload__account_id=account_id,
        ).exists()

    @staticmethod
    def same_file_transaction_exists(
        account_id: int,
        source_file_hash: str,
        source_row_position: int,
    ) -> bool:
        """Tell whether this file position is already posted."""
        if not source_file_hash:
            return False
        return Transaction.objects.filter(
            account_id=account_id,
            source_file_hash=source_file_hash,
            source_row_position=source_row_position,
        ).exists()

    @staticmethod
    def save_upload_bank_code(
        upload: BankStatementUpload,
        bank_code: str,
    ) -> None:
        """Persist the immutable parser provenance of the upload."""
        upload.source_bank_code = bank_code
        upload.save(update_fields=['source_bank_code'])

    @staticmethod
    def upload_account_id(upload_id: int) -> int | None:
        """Return the upload's account to lock before the upload row."""
        return (
            BankStatementUpload.objects.filter(pk=upload_id)
            .values_list('account_id', flat=True)
            .first()
        )

    @staticmethod
    def lock_upload(upload_id: int) -> BankStatementUpload | None:
        """Lock one upload row after its account; None if it is gone."""
        return (
            BankStatementUpload.objects.select_for_update()
            .filter(pk=upload_id)
            .first()
        )

    @staticmethod
    def save_failed_upload(
        upload: BankStatementUpload,
        message: str,
    ) -> None:
        """Persist a failure without touching parsed bank data."""
        upload.status = BankStatementUpload.Status.FAILED
        upload.failed_count = 1
        upload.error_message = message
        upload.save(
            update_fields=[
                'status',
                'failed_count',
                'error_message',
                'updated_at',
            ],
        )

    @staticmethod
    def has_upload_rows(
        upload_id: int,
        decisions: Sequence[str],
    ) -> bool:
        """Tell whether the upload keeps rows in any of these decisions."""
        return BankStatementRow.objects.filter(
            upload_id=upload_id,
            decision__in=decisions,
        ).exists()

    @staticmethod
    def recover_parse_error_row(
        row_id: int,
        defaults: dict[str, Any],
    ) -> int:
        """Rewrite one still-unparsed row after its position parses again.

        The decision guard keeps an owner decision that arrived between the
        two imports; the caller owns the surrounding transaction.
        """
        return BankStatementRow.objects.filter(
            pk=row_id,
            decision=BankStatementRow.Decision.PARSE_ERROR,
        ).update(resume_decision='', **defaults)

    @staticmethod
    def save_upload_fields(
        upload: BankStatementUpload,
        fields: Sequence[str],
    ) -> None:
        """Persist lifecycle fields computed by the import service."""
        upload.save(update_fields=fields)

    @staticmethod
    def create_manual_row(
        *,
        upload: BankStatementUpload,
        source_row_position: int,
        defaults: dict[str, object],
    ) -> BankStatementRow:
        """Create or reuse the manual representation of one parsed row."""
        row, _created = BankStatementRow.objects.get_or_create(
            upload=upload,
            source_row_position=source_row_position,
            defaults=defaults,
        )
        return row

    @staticmethod
    def add_statement_candidates(
        row: BankStatementRow,
        candidates: Sequence[tuple[Transaction, str]],
    ) -> None:
        """Attach already stored movements as manual review candidates."""
        BankStatementCandidate.objects.bulk_create(
            [
                BankStatementCandidate(
                    row=row,
                    transaction=movement,
                    description=description[:250],
                    rank=rank,
                )
                for rank, (movement, description) in enumerate(candidates)
            ],
            ignore_conflicts=True,
        )
