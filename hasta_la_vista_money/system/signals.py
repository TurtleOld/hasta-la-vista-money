"""Audit logging for financial model changes."""

from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.db import models
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils.encoding import force_str
from django.utils.functional import Promise

from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.system.models import AuditLog
from hasta_la_vista_money.users.models import User

AUDITED_MODELS = (Account, Expense, Income, Receipt, TransferMoneyLog)
_ORIGINAL_STATE_ATTR = '_audit_original_state'


def _iter_concrete_fields(instance: models.Model) -> Iterable[models.Field]:
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


def _snapshot(instance: models.Model) -> dict[str, Any]:
    return {
        field.attname: _serialize_value(getattr(instance, field.attname))
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


def _create_audit_log(
    *,
    instance: models.Model,
    action: str,
    diff: dict[str, Any],
) -> None:
    AuditLog.objects.create(
        user=_get_user(instance),
        model_name=instance._meta.label,
        object_pk=str(instance.pk),
        action=action,
        diff=diff,
    )


@receiver(pre_save)
def store_original_state(sender, instance: models.Model, **kwargs) -> None:
    del kwargs
    if sender not in AUDITED_MODELS or instance.pk is None:
        return

    old_instance = sender.objects.filter(pk=instance.pk).first()
    if old_instance is None:
        return

    setattr(instance, _ORIGINAL_STATE_ATTR, _snapshot(old_instance))


@receiver(post_save)
def audit_saved_instance(
    sender,
    instance: models.Model,
    created: bool,
    **kwargs,
) -> None:
    del kwargs
    if sender not in AUDITED_MODELS:
        return

    new_state = _snapshot(instance)
    if created:
        _create_audit_log(
            instance=instance,
            action=AuditLog.Action.CREATE,
            diff={'created': new_state},
        )
        return

    old_state = getattr(instance, _ORIGINAL_STATE_ATTR, {})
    changes = _diff(old_state, new_state)
    if changes:
        _create_audit_log(
            instance=instance,
            action=AuditLog.Action.UPDATE,
            diff=changes,
        )


@receiver(post_delete)
def audit_deleted_instance(sender, instance: models.Model, **kwargs) -> None:
    del kwargs
    if sender not in AUDITED_MODELS:
        return

    _create_audit_log(
        instance=instance,
        action=AuditLog.Action.DELETE,
        diff={'deleted': _snapshot(instance)},
    )
