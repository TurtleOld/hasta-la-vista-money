"""Remove raw legacy bank IDs without inventing their bank provenance.

Raw references cannot be recovered on rollback. Reversing this migration
only permits schema rollback; it does not restore deleted identifiers.
Configure a stable statement HMAC key before migrating an existing install.
Unknown historical bank context never becomes trusted exact identity.
"""

import hashlib
import hmac
import json
from collections import Counter
from typing import Any, Final

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import migrations, transaction
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

# Historical formats must not follow later runtime parameter changes.
HMAC_V1_MIN_KEY_BYTES: Final = 32
HMAC_V1_KEY_ID_MAX_LENGTH: Final = 64


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise ImproperlyConfigured('Invalid statement HMAC configuration')
        result[name] = value
    return result


def _load_v1_key() -> tuple[str, bytes]:
    """Freeze v1 config validation; never depend on future runtime formats."""
    error = 'Configure a stable statement identity HMAC key before migrating'
    active = getattr(settings, 'STATEMENT_ID_HMAC_ACTIVE_KEY_ID', '')
    raw = getattr(settings, 'STATEMENT_ID_HMAC_KEYS', '')
    try:
        parsed = json.loads(raw, object_pairs_hook=_unique_keys)
    except (TypeError, ValueError):
        raise ImproperlyConfigured(error) from None
    if not isinstance(parsed, dict) or not isinstance(active, str):
        raise ImproperlyConfigured(error)
    keys: dict[str, bytes] = {}
    for name, value in parsed.items():
        if (
            not isinstance(name, str)
            or not name
            or len(name) > HMAC_V1_KEY_ID_MAX_LENGTH
            or not isinstance(value, str)
        ):
            raise ImproperlyConfigured(error)
        try:
            decoded = bytes.fromhex(value)
        except ValueError:
            raise ImproperlyConfigured(error) from None
        if len(decoded) < HMAC_V1_MIN_KEY_BYTES:
            raise ImproperlyConfigured(error)
        keys[name] = decoded
    if active not in keys:
        raise ImproperlyConfigured(error)
    return active, keys[active]


def _fingerprint_v1(key: bytes, account_id: int, reference: str) -> str:
    message = json.dumps(
        [1, 'legacy-unverified', account_id, reference.strip()],
        ensure_ascii=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def fingerprint_legacy_references(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    alias = schema_editor.connection.alias
    row_model = apps.get_model('users', 'BankStatementRow')
    movement_model = apps.get_model('transactions', 'Transaction')
    models = (row_model, movement_model)
    has_unhashed_refs = any(
        any(
            reference.strip()
            for reference in model.objects.using(alias)
            .filter(source_ref__isnull=False, source_ref_hash__isnull=True)
            .values_list('source_ref', flat=True)
            .iterator()
        )
        for model in models
    )
    # Validate before writes. Invalid whitespace-only IDs carry no identity.
    key_id, key = _load_v1_key() if has_unhashed_refs else ('', b'')
    with transaction.atomic(using=alias):
        for model in models:
            records = model.objects.using(alias).exclude(source_ref=None)
            for record in records.iterator():
                account_id = (
                    record.upload.account_id
                    if model is row_model
                    else record.account_id
                )
                updates: dict[str, object] = {
                    'source_ref': None,
                    'source_identity_trusted': False,
                }
                if record.source_ref.strip() and record.source_ref_hash is None:
                    updates.update(
                        source_ref_hash=_fingerprint_v1(
                            key,
                            account_id,
                            record.source_ref,
                        ),
                        source_ref_key_id=key_id,
                        source_ref_version=1,
                    )
                model.objects.using(alias).filter(pk=record.pk).update(
                    **updates,
                )
        _scrub_audit(apps, alias)


def _redact_references(value: Any) -> bool:
    """Frozen migration rule: remove bank IDs, preserve financial fields."""
    marker = '[bank identifier removed]'
    changed = False
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'source_ref':
                if isinstance(item, dict):
                    for side in ('old', 'new'):
                        if item.get(side) not in (None, '', marker):
                            item[side] = marker
                            changed = True
                elif item not in (None, '', marker):
                    value[key] = marker
                    changed = True
            else:
                changed = _redact_references(item) or changed
    elif isinstance(value, list):
        for item in value:
            changed = _redact_references(item) or changed
    return changed


def _scrub_audit(apps: StateApps, alias: str) -> None:
    audit_model = apps.get_model('system', 'AuditLog')
    changed_by_user: Counter[int | None] = Counter()
    audits = audit_model.objects.using(alias).filter(
        model_name__in=['transactions.Transaction', 'transactions.transaction'],
    )
    for audit in audits.iterator():
        diff = audit.diff
        if _redact_references(diff):
            audit_model.objects.using(alias).filter(pk=audit.pk).update(
                diff=diff,
            )
            changed_by_user[audit.user_id] += 1
    for user_id, count in changed_by_user.items():
        audit_model.objects.using(alias).create(
            user_id=user_id,
            model_name='users.BankStatementUpload',
            object_pk='legacy-identity-migration-v1',
            action='update',
            kind='statement_import_resolution',
            diff={
                'bank_identifiers_anonymized': {'old': False, 'new': True},
                'entries': {'old': None, 'new': count},
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ('users', '0026_bankstatementrow_data_cleaned_at_and_more'),
        ('transactions', '0007_transaction_source_identity_trusted_and_more'),
        ('system', '0007_statement_markup'),
    ]

    operations = [
        migrations.RunPython(
            fingerprint_legacy_references,
            migrations.RunPython.noop,
        ),
    ]
