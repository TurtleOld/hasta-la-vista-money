"""Anonymise raw statement references in existing financial audit entries.

Retention removes the bank's own copy of a statement identifier. The
movement's audit entry may still hold the raw value under ``source_ref``,
so this helper replaces just that value while keeping the event, author,
time, money and category. The lead runs it after converting the stored
identifiers to HMAC fingerprints; it is deliberately separate from cleanup.
"""

from collections import Counter
from collections.abc import Iterable
from typing import Any

from django.db import transaction

from hasta_la_vista_money.system.models import AuditLog, AuditOperationKind
from hasta_la_vista_money.system.services.audit_context import (
    audit_operation,
    current_operation_id,
    current_operation_kind,
)

STATEMENT_SOURCE_REF_SCRUBBED_LABEL = '[банковский идентификатор удалён]'
STATEMENT_SCRUB_FACT_OBJECT = 'statement-audit-scrub-v1'


def _scrub_ref(item: Any) -> bool:
    """Replace an old/new pair or a plain raw value; report a change."""
    if isinstance(item, dict):
        changed = False
        for side in ('old', 'new'):
            side_value = item.get(side)
            if side_value in (None, '', STATEMENT_SOURCE_REF_SCRUBBED_LABEL):
                continue
            item[side] = STATEMENT_SOURCE_REF_SCRUBBED_LABEL
            changed = True
        return changed
    return item not in (None, '', STATEMENT_SOURCE_REF_SCRUBBED_LABEL)


def _scrub_source_refs(value: Any) -> bool:
    """Replace every non-empty ``source_ref`` value inside a diff."""
    if isinstance(value, dict):
        changed = False
        for key, item in value.items():
            if key == 'source_ref':
                if isinstance(item, dict):
                    changed = _scrub_ref(item) or changed
                elif _scrub_ref(item):
                    value[key] = STATEMENT_SOURCE_REF_SCRUBBED_LABEL
                    changed = True
            elif _scrub_source_refs(item):
                changed = True
        return changed
    if isinstance(value, list):
        changed = False
        for item in value:
            changed = _scrub_source_refs(item) or changed
        return changed
    return False


def scrub_transaction_source_ref_audit(
    transaction_ids: Iterable[int],
) -> int:
    """Scrub raw source refs in the audit of the given transactions.

    Returns the number of audit entries actually changed, so a repeated
    run reports zero and leaves the stored diffs untouched. The
    anonymisation fact belongs to the current audit operation when one is
    active; a standalone run mints its own resolution operation instead of
    writing an entry with a null ``operation_id``.
    """
    wanted = {str(pk) for pk in transaction_ids}
    if not wanted:
        return 0
    if current_operation_id() is None:
        with audit_operation(
            kind=AuditOperationKind.STATEMENT_IMPORT_RESOLUTION,
        ):
            return _scrub_source_refs_and_record(wanted)
    return _scrub_source_refs_and_record(wanted)


def _scrub_source_refs_and_record(wanted: set[str]) -> int:
    """Rewrite the diffs and record the anonymisation fact."""
    operation_id = current_operation_id()
    operation_kind = current_operation_kind()
    changed_by_user: Counter[int | None] = Counter()
    with transaction.atomic():
        logs = AuditLog.objects.filter(
            model_name='transactions.Transaction',
            object_pk__in=wanted,
        ).select_for_update()
        for log in logs.iterator():
            diff = log.diff
            if _scrub_source_refs(diff):
                log.diff = diff
                log.save(update_fields=['diff'])
                changed_by_user[log.user_id] += 1
        changed = sum(changed_by_user.values())
        for user_id, count in changed_by_user.items():
            AuditLog.objects.create(
                user_id=user_id,
                model_name='users.BankStatementUpload',
                object_pk=STATEMENT_SCRUB_FACT_OBJECT,
                action=AuditLog.Action.UPDATE,
                kind=operation_kind,
                operation_id=operation_id,
                diff={
                    'bank_identifiers_anonymized': {
                        'old': False,
                        'new': True,
                    },
                    'entries': {'old': None, 'new': count},
                },
            )
    return changed
