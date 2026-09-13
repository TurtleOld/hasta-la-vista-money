"""Write-side summary of a bank statement import run.

``process_bank_statement`` and ``process_bank_statement_task`` write
Transaction and Account audit entries under one ``audit_operation(kind=
STATEMENT_IMPORT)`` for the whole run. None of those entries alone carries
the run's own facts — the account, how many rows were created versus
skipped as duplicates, and the date span of what was imported — and a run
whose rows all turned out to be duplicates writes no such entries at all.
This module records one extra entry per run holding exactly those facts,
unconditionally, so the run is never invisible in the feed; audit_feed.py
reads it back to build the operation's caption instead of disclosing every
entry.
"""

from datetime import date

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.system.audit_registry import STATEMENT_IMPORT_LABEL
from hasta_la_vista_money.system.models import AuditLog
from hasta_la_vista_money.system.services.audit_context import (
    current_operation_id,
    current_operation_kind,
)
from hasta_la_vista_money.users.models import User


def record_statement_import_summary(
    *,
    user: User,
    account: Account,
    created: int,
    skipped_duplicates: int,
    period_from: date | None,
    period_to: date | None,
) -> None:
    """Record the one entry describing an import run's own facts."""
    AuditLog.objects.create(
        user=user,
        model_name=STATEMENT_IMPORT_LABEL,
        object_pk=str(account.pk),
        object_name=account.name_account,
        action=AuditLog.Action.CREATE,
        diff={
            'created': created,
            'skipped_duplicates': skipped_duplicates,
            'period_from': period_from.isoformat() if period_from else None,
            'period_to': period_to.isoformat() if period_to else None,
        },
        operation_id=current_operation_id(),
        kind=current_operation_kind(),
    )
