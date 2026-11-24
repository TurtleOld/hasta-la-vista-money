"""Shared rules for claiming that a bank statement upload is complete.

Completion depends on saved row decisions and on a non-empty parse. A
resolved row alone is not enough: every decision that still needs the
owner keeps the statement open, and an empty parse never proves that the
statement had no operations.
"""

from typing import Final

from django.db.models import QuerySet

from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
)

UNRESOLVED_DECISIONS: Final = frozenset(
    {
        BankStatementRow.Decision.PENDING,
        BankStatementRow.Decision.AWAITING_MARKUP,
        BankStatementRow.Decision.NEEDS_TRANSFER,
    },
)


def unresolved_rows(
    upload: BankStatementUpload,
) -> QuerySet[BankStatementRow]:
    """Return rows whose decision still needs the owner's action."""
    return BankStatementRow.objects.filter(
        upload=upload,
        decision__in=UNRESOLVED_DECISIONS,
    )


def has_unresolved_rows(upload: BankStatementUpload) -> bool:
    """Return whether the upload keeps any unresolved saved row."""
    return unresolved_rows(upload).exists()


def is_statement_complete(upload: BankStatementUpload) -> bool:
    """Return whether saved rows prove a complete, non-empty parse."""
    rows = BankStatementRow.objects.filter(upload=upload)
    has_evidence = upload.total_transactions > 0 or rows.exists()
    return (
        has_evidence
        and not rows.filter(
            decision__in=UNRESOLVED_DECISIONS,
        ).exists()
    )
