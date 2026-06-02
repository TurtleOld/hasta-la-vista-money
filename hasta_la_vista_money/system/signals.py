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

FIELD_VERBOSE_NAMES: dict[str, dict[str, str]] = {
    'finance_account.Account': {
        'name_account': 'Название счёта',
        'type_account': 'Тип счёта',
        'bank': 'Банк',
        'balance': 'Баланс',
        'currency': 'Валюта',
        'limit_credit': 'Кредитный лимит',
        'payment_due_date': 'Дата платежа',
        'grace_period_days': 'Льготный период (дней)',
        'user_id': 'Пользователь',
        'created_at': 'Дата создания',
        'updated_at': 'Дата обновления',
    },
    'transactions.Transaction': {
        'type': 'Тип',
        'date': 'Дата',
        'amount': 'Сумма',
        'account_id': 'Счёт',
        'category_id': 'Категория',
        'user_id': 'Пользователь',
        'source_ref': 'ID операции в выписке',
        'created_at': 'Дата создания',
    },
    'receipts.Receipt': {
        'receipt_date': 'Дата чека',
        'seller_id': 'Продавец',
        'account_id': 'Счёт',
        'user_id': 'Пользователь',
        'total_sum': 'Сумма',
        'operation_type': 'Тип операции',
        'created_at': 'Дата создания',
        'updated_at': 'Дата обновления',
    },
    'finance_account.TransferMoneyLog': {
        'from_account_id': 'Счёт списания',
        'to_account_id': 'Счёт зачисления',
        'amount': 'Сумма',
        'exchange_date': 'Дата перевода',
        'notes': 'Примечания',
        'user_id': 'Пользователь',
        'created_at': 'Дата создания',
        'updated_at': 'Дата обновления',
    },
}

FK_RESOLVERS: dict[str, Any] = {
    'account_id': lambda pk: _resolve_account_name(pk),
    'from_account_id': lambda pk: _resolve_account_name(pk),
    'to_account_id': lambda pk: _resolve_account_name(pk),
}

HIDDEN_FIELDS = frozenset({'id', 'user_id', 'updated_at'})


def _resolve_account_name(pk: Any) -> str:
    if pk is None:
        return '—'
    try:
        return Account.objects.values_list('name_account', flat=True).get(pk=pk)
    except Account.DoesNotExist:
        return f'(удалён, id={pk})'


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


def _resolve_fk_values(
    model_label: str,
    raw_data: dict[str, Any],
) -> dict[str, Any]:
    """Replace FK ids with human-readable names and rename fields to verbose."""
    verbose_map = FIELD_VERBOSE_NAMES.get(model_label, {})
    result: dict[str, Any] = {}
    for field_name, value in raw_data.items():
        if field_name in HIDDEN_FIELDS:
            continue
        resolver = FK_RESOLVERS.get(field_name)
        display_value = resolver(value) if resolver else value
        display_name = verbose_map.get(field_name, field_name)
        result[display_name] = display_value
    return result


def _diff(
    old_state: dict[str, Any],
    new_state: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        field_name: {'old': old_state.get(field_name), 'new': new_value}
        for field_name, new_value in new_state.items()
        if old_state.get(field_name) != new_value
    }


def _diff_verbose(
    model_label: str,
    old_state: dict[str, Any],
    new_state: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Diff with verbose names and resolved FK values."""
    verbose_map = FIELD_VERBOSE_NAMES.get(model_label, {})
    result: dict[str, dict[str, Any]] = {}
    for field_name, new_raw in new_state.items():
        if field_name in HIDDEN_FIELDS:
            continue
        old_raw = old_state.get(field_name)
        if old_raw == new_raw:
            continue
        resolver = FK_RESOLVERS.get(field_name)
        old_display = resolver(old_raw) if resolver else old_raw
        new_display = resolver(new_raw) if resolver else new_raw
        display_name = verbose_map.get(field_name, field_name)
        result[display_name] = {'old': old_display, 'new': new_display}
    return result


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

    object_name = _get_object_name(instance)
    new_state = _snapshot(instance)
    if created:
        _create_audit_log(
            instance=instance,
            action=AuditLog.Action.CREATE,
            diff={
                'created': _resolve_fk_values(instance._meta.label, new_state),
            },
            object_name=object_name,
        )
        return

    old_state = getattr(instance, _ORIGINAL_STATE_ATTR, {})
    changes = _diff_verbose(instance._meta.label, old_state, new_state)
    if changes:
        _create_audit_log(
            instance=instance,
            action=AuditLog.Action.UPDATE,
            diff=changes,
            object_name=object_name,
        )


@receiver(post_delete)
def audit_deleted_instance(sender, instance: models.Model, **kwargs) -> None:
    del kwargs
    if sender not in AUDITED_MODELS:
        return

    object_name = _get_object_name(instance)
    _create_audit_log(
        instance=instance,
        action=AuditLog.Action.DELETE,
        diff={
            'deleted': _resolve_fk_values(
                instance._meta.label,
                _snapshot(instance),
            ),
        },
        object_name=object_name,
    )
