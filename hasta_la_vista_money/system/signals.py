"""Audit logging for financial model changes.

The write layer records facts, not their presentation: every changed field
lands in ``diff`` under its raw ``attname`` with a raw value. What of that
is shown to the user is decided on read by the audited field registry.
"""

from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

from django.db import models
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils.encoding import force_str
from django.utils.functional import Promise

from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.system.models import AuditLog
from hasta_la_vista_money.transactions.models import Transaction
from hasta_la_vista_money.users.models import User

AUDITED_MODELS = (Account, Transaction, Receipt, TransferMoneyLog)
_ORIGINAL_STATE_ATTR = '_audit_original_state'

#: Format of ``AuditLog.diff`` written by these signals. Entries stored
#: before the registry carry no version and are read as version 1.
AUDIT_DIFF_VERSION: Final = 2


def _iter_concrete_fields(
    instance: models.Model,
) -> Iterable[models.Field[Any, Any]]:
    return (
        field
        for field in instance._meta.concrete_fields
        if not getattr(field, 'auto_created', False)
    )


def _serialize_value(value: Any) -> Any:
    if isinstance(value, Promise):
        return force_str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _normalize_value(field: models.Field[Any, Any], value: Any) -> Any:
    """Bring a value to the field's own type.

    Without it a freshly assigned ``0`` and a ``Decimal('0.00')`` read back
    from the database look like a change of the balance.
    """
    if value is None:
        return None
    typed_value = field.to_python(value)
    if isinstance(field, models.DecimalField) and field.decimal_places:
        exponent = Decimal(1).scaleb(-field.decimal_places)
        return Decimal(typed_value).quantize(exponent)
    return typed_value


def _snapshot(instance: models.Model) -> dict[str, Any]:
    return {
        field.attname: _serialize_value(
            _normalize_value(field, getattr(instance, field.attname)),
        )
        for field in _iter_concrete_fields(instance)
    }


def _diff(
    old_state: dict[str, Any],
    new_state: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        field_name: {'old': old_state.get(field_name), 'new': new_value}
        for field_name, new_value in new_state.items()
        if old_state.get(field_name) != new_value
    }


def _get_user(instance: models.Model) -> User | None:
    user = getattr(instance, 'user', None)
    return user if isinstance(user, User) else None


def _get_object_name(instance: models.Model) -> str:
    """Return human-readable name of the audited object."""
    if isinstance(instance, Account):
        return instance.name_account
    if isinstance(instance, TransferMoneyLog):
        from_name = (
            instance.from_account.name_account if instance.from_account else '—'
        )
        to_name = (
            instance.to_account.name_account if instance.to_account else '—'
        )
        return f'{from_name} → {to_name}'
    if isinstance(instance, Transaction):
        return instance.account.name_account if instance.account_id else '—'
    if isinstance(instance, Receipt):
        return instance.account.name_account if instance.account_id else '—'
    return str(instance.pk)


def _create_audit_log(
    *,
    instance: models.Model,
    action: str,
    diff: dict[str, Any],
    object_name: str = '',
) -> None:
    AuditLog.objects.create(
        user=_get_user(instance),
        model_name=instance._meta.label,
        object_pk=str(instance.pk),
        object_name=object_name,
        action=action,
        diff={'v': AUDIT_DIFF_VERSION, **diff},
    )


@receiver(pre_save)
def store_original_state(
    sender: type[models.Model],
    instance: models.Model,
    **kwargs: Any,
) -> None:
    del kwargs
    if sender not in AUDITED_MODELS or instance.pk is None:
        return

    old_instance = sender._default_manager.filter(pk=instance.pk).first()
    if old_instance is None:
        return

    setattr(instance, _ORIGINAL_STATE_ATTR, _snapshot(old_instance))


@receiver(post_save)
def audit_saved_instance(
    sender: type[models.Model],
    instance: models.Model,
    created: bool,
    **kwargs: Any,
) -> None:
    del kwargs
    if sender not in AUDITED_MODELS:
        return

    object_name = _get_object_name(instance)
    new_state = _snapshot(instance)
    if created:
        _create_audit_log(
            instance=instance,
            action=AuditLog.Action.CREATE,
            diff={'created': new_state},
            object_name=object_name,
        )
        return

    old_state = getattr(instance, _ORIGINAL_STATE_ATTR, {})
    changes = _diff(old_state, new_state)
    if changes:
        _create_audit_log(
            instance=instance,
            action=AuditLog.Action.UPDATE,
            diff={'changed': changes},
            object_name=object_name,
        )


@receiver(post_delete)
def audit_deleted_instance(
    sender: type[models.Model],
    instance: models.Model,
    **kwargs: Any,
) -> None:
    del kwargs
    if sender not in AUDITED_MODELS:
        return

    _create_audit_log(
        instance=instance,
        action=AuditLog.Action.DELETE,
        diff={'deleted': _snapshot(instance)},
        object_name=_get_object_name(instance),
    )
