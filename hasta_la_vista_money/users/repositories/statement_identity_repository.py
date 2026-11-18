"""ORM access for bank statement identity fingerprints.

The repository only answers questions about stored fingerprints; whether a
match is an exact duplicate, a manual candidate, or a reason to fail closed
is decided by ``StatementIdentityService``.
"""

from collections.abc import Iterable

from django.db.models import Q, QuerySet

from hasta_la_vista_money.transactions.models import Transaction
from hasta_la_vista_money.users.models import BankStatementRow

_UNTRUSTED = Q(
    source_ref_hash__isnull=False,
    source_identity_trusted=False,
)


class StatementIdentityRepository:
    """Stored statement fingerprints of one account."""

    @staticmethod
    def trusted_exact_transaction_exists(
        account_id: int,
        digests: Iterable[str],
    ) -> bool:
        """Tell whether a trusted movement already owns one of the digests."""
        wanted = set(digests)
        if not wanted:
            return False
        return Transaction.objects.filter(
            account_id=account_id,
            source_ref_hash__in=wanted,
            source_identity_trusted=True,
        ).exists()

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
        """Tell whether the account keeps unverified historical fingerprints.

        A nonmatch is not proof of absence while such records exist: they
        may describe the same operation under an unknown bank namespace.
        """
        if Transaction.objects.filter(
            _UNTRUSTED,
            account_id=account_id,
        ).exists():
            return True
        return BankStatementRow.objects.filter(
            _UNTRUSTED,
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
    def statement_rows_for_digests(
        account_id: int,
        digests: Iterable[str],
    ) -> QuerySet[BankStatementRow]:
        """Return statement rows of the account owning one of the digests."""
        wanted = set(digests)
        if not wanted:
            return BankStatementRow.objects.none()
        return BankStatementRow.objects.filter(
            upload__account_id=account_id,
            source_ref_hash__in=wanted,
        )

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
