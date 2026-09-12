"""Rendering of audit entries through the audited field registry.

The registry is applied here, on read: an entry keeps every changed field,
this module decides which of them the user sees and how they are printed.
Entries written before the registry (``diff`` without ``v``) are printed as
they were stored — neither the whitelist nor the formatters touch them.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Final

from django.apps import apps
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money.system.audit_registry import (
    ACCOUNT_LABEL,
    AUDIT_FIELDS,
    MODEL_LABELS,
    AuditField,
    CurrencySource,
    Formatter,
    Related,
)
from hasta_la_vista_money.system.models import AuditLog
from hasta_la_vista_money.system.signals import AUDIT_DIFF_VERSION

if TYPE_CHECKING:
    from django.db import models

NBSP: Final = ' '
EMPTY: Final = '—'
DATE_FORMAT: Final = '%d.%m.%Y'
DATETIME_FORMAT: Final = '%d.%m.%Y %H:%M'

_MONEY_EXPONENT: Final = Decimal('0.01')

_MOMENT_FORMATS: Final[Mapping[Formatter, str]] = {
    Formatter.DATE: DATE_FORMAT,
    Formatter.DATETIME: DATETIME_FORMAT,
}

_RELATED_SOURCES: Final[Mapping[Related, tuple[str, str]]] = {
    Related.ACCOUNT: (ACCOUNT_LABEL, 'name_account'),
    Related.SELLER: ('receipts.Seller', 'name_seller'),
    Related.CATEGORY: ('transactions.Category', 'name'),
    Related.BANK: ('finance_account.Bank', 'name'),
}


class _Absent:
    """Marker for a side of a change that does not exist."""


ABSENT: Final = _Absent()


@dataclass(frozen=True)
class RenderedChange:
    """One field of an audit entry, ready to be printed."""

    label: str
    old: str | None
    new: str | None
    attname: str = ''


@dataclass(frozen=True)
class BalanceEffect:
    """One account's contribution to an operation: before → move → after."""

    account_name: str
    before: str
    movement: str
    after: str
    negative: bool


@dataclass(frozen=True)
class RenderedEntry:
    """An audit entry together with its visible changes."""

    entry: AuditLog
    changes: list[RenderedChange] = field(default_factory=list)
    legacy: bool = False
    balance_effect: BalanceEffect | None = None
    header: str = ''

    @property
    def has_changes(self) -> bool:
        return bool(self.changes)


def _entry_header(entry: AuditLog) -> str:
    """Build the "model · object" half of the disclosure group heading.

    Only the account model gets its object name quoted onto the label —
    it is the only one where several instances of the same model can
    appear side by side in one operation and need telling apart.
    """
    label = MODEL_LABELS.get(entry.model_name)
    if label is None:
        return entry.object_name or entry.model_name
    if entry.model_name == ACCOUNT_LABEL and entry.object_name:
        return f'{label} «{entry.object_name}»'
    return str(label)


def render_entries(entries: Sequence[AuditLog]) -> list[RenderedEntry]:
    """Render a page of audit entries, resolving lookups in batches."""
    raw_pages = [(entry, _raw_sides(entry)) for entry in entries]
    context = _ReadContext(raw_pages)
    return [_render_entry(entry, sides, context) for entry, sides in raw_pages]


def entry_has_visible_change(entry: AuditLog) -> bool:
    """Whether rendering ``entry`` would show at least one change.

    Cheaper than :func:`render_entries`: it skips the batched FK and
    currency lookups and only checks which fields would be shown.
    """
    diff = entry.diff or {}
    if _is_legacy(diff):
        return bool(_legacy_changes(diff))
    return bool(_visible_fields(entry, _raw_sides(entry)))


def _is_legacy(diff: Mapping[str, Any]) -> bool:
    return diff.get('v') != AUDIT_DIFF_VERSION


def _raw_sides(entry: AuditLog) -> dict[str, tuple[Any, Any]]:
    """Return ``attname -> (old, new)`` of the entry payload."""
    diff = entry.diff or {}
    if _is_legacy(diff):
        return {}
    if 'created' in diff:
        return {
            name: (ABSENT, value) for name, value in diff['created'].items()
        }
    if 'deleted' in diff:
        return {
            name: (value, ABSENT) for name, value in diff['deleted'].items()
        }
    changed = diff.get('changed') or {}
    return {
        name: (sides.get('old'), sides.get('new'))
        for name, sides in changed.items()
    }


def _registry_for(entry: AuditLog) -> Mapping[str, AuditField]:
    return AUDIT_FIELDS.get(entry.model_name, {})


def _visible_fields(
    entry: AuditLog,
    sides: Mapping[str, tuple[Any, Any]],
) -> list[tuple[str, AuditField]]:
    """Fields of the entry present in the registry, in registry order."""
    return [
        (attname, audit_field)
        for attname, audit_field in _registry_for(entry).items()
        if attname in sides
    ]


class _ReadContext:
    """Batched lookups needed to print one page of audit entries."""

    def __init__(
        self,
        raw_pages: Sequence[tuple[AuditLog, Mapping[str, tuple[Any, Any]]]],
    ) -> None:
        self._related: dict[Related, dict[Any, str]] = {}
        self._currency_by_account: dict[Any, str] = {}
        self._account_by_object: dict[tuple[str, Any], Any] = {}
        self._collect(raw_pages)

    def related_name(self, related: Related, pk: Any) -> str:
        if pk is None:
            return EMPTY
        name = self._related.get(related, {}).get(pk)
        return name or str(_('(удалён, id=%(pk)s)') % {'pk': pk})

    def currency_for(
        self,
        entry: AuditLog,
        sides: Mapping[str, tuple[Any, Any]],
        source: CurrencySource,
        *,
        old_side: bool,
    ) -> str:
        if source is CurrencySource.SELF and 'currency' in sides:
            return _requested_side(sides['currency'], old_side=old_side)
        account_pk = self._account_pk(
            entry,
            sides,
            source,
            old_side=old_side,
        )
        return self._currency_by_account.get(account_pk, '')

    def _account_pk(
        self,
        entry: AuditLog,
        sides: Mapping[str, tuple[Any, Any]],
        source: CurrencySource,
        *,
        old_side: bool,
    ) -> Any:
        if source is CurrencySource.SELF:
            return _as_pk(entry.object_pk)
        attname = source.value
        if attname in sides:
            return _side_pk(sides[attname], old_side=old_side)
        return self._account_by_object.get(
            (entry.model_name, _as_pk(entry.object_pk)),
        )

    def _collect(
        self,
        raw_pages: Sequence[tuple[AuditLog, Mapping[str, tuple[Any, Any]]]],
    ) -> None:
        related_ids: dict[Related, set[Any]] = {}
        account_ids: set[Any] = set()
        object_lookups: dict[tuple[str, str], set[Any]] = {}
        for entry, sides in raw_pages:
            for attname, audit_field in _visible_fields(entry, sides):
                if audit_field.related is not None:
                    ids = related_ids.setdefault(audit_field.related, set())
                    ids.update(_both_sides(sides[attname]))
                if audit_field.currency_from is not None:
                    self._plan_currency(
                        entry,
                        sides,
                        audit_field.currency_from,
                        account_ids,
                        object_lookups,
                    )
        self._resolve_objects(object_lookups, account_ids)
        self._resolve_related(related_ids)
        self._resolve_currencies(account_ids)

    def _plan_currency(
        self,
        entry: AuditLog,
        sides: Mapping[str, tuple[Any, Any]],
        source: CurrencySource,
        account_ids: set[Any],
        object_lookups: dict[tuple[str, str], set[Any]],
    ) -> None:
        if source is CurrencySource.SELF:
            if 'currency' not in sides:
                account_ids.add(_as_pk(entry.object_pk))
            return
        attname = source.value
        if attname in sides:
            account_ids.update(_both_sides(sides[attname]))
            return
        key = (entry.model_name, attname)
        object_lookups.setdefault(key, set()).add(_as_pk(entry.object_pk))

    def _resolve_objects(
        self,
        object_lookups: Mapping[tuple[str, str], set[Any]],
        account_ids: set[Any],
    ) -> None:
        for (model_label, attname), pks in object_lookups.items():
            rows = _values_list(model_label, ('pk', attname), pks)
            for pk, account_pk in rows:
                self._account_by_object[(model_label, pk)] = account_pk
                account_ids.add(account_pk)

    def _resolve_related(
        self,
        related_ids: Mapping[Related, set[Any]],
    ) -> None:
        for related, pks in related_ids.items():
            model_label, name_attname = _RELATED_SOURCES[related]
            rows = _values_list(model_label, ('pk', name_attname), pks)
            self._related[related] = dict(rows)

    def _resolve_currencies(self, account_ids: set[Any]) -> None:
        rows = _values_list(
            ACCOUNT_LABEL,
            ('pk', 'currency'),
            account_ids,
        )
        self._currency_by_account = dict(rows)


def _values_list(
    model_label: str,
    fields: tuple[str, str],
    pks: Iterable[Any],
) -> list[tuple[Any, Any]]:
    known = {pk for pk in pks if pk is not None}
    if not known:
        return []
    model: type[models.Model] = apps.get_model(model_label)
    queryset = model._default_manager.filter(pk__in=known)
    return list(queryset.values_list(*fields))


def _both_sides(sides: tuple[Any, Any]) -> set[Any]:
    return {value for value in sides if not isinstance(value, _Absent)}


def _side_pk(sides: tuple[Any, Any], *, old_side: bool) -> Any:
    """Referenced id of the asked side, falling back to the other one."""
    value = sides[0] if old_side else sides[1]
    return _side_value(sides) if isinstance(value, _Absent) else value


def _requested_side(sides: tuple[Any, Any], *, old_side: bool) -> str:
    """Value of the asked side, falling back to the side that exists."""
    value = sides[0] if old_side else sides[1]
    if isinstance(value, _Absent):
        value = _side_value(sides)
    return '' if value is None else str(value)


def _side_value(sides: tuple[Any, Any]) -> Any:
    old_value, new_value = sides
    if not isinstance(new_value, _Absent):
        return new_value
    return None if isinstance(old_value, _Absent) else old_value


def _as_pk(object_pk: str) -> Any:
    try:
        return int(object_pk)
    except (TypeError, ValueError):
        return object_pk


def _render_entry(
    entry: AuditLog,
    sides: Mapping[str, tuple[Any, Any]],
    context: _ReadContext,
) -> RenderedEntry:
    if _is_legacy(entry.diff or {}):
        return RenderedEntry(
            entry=entry,
            changes=_legacy_changes(entry.diff or {}),
            legacy=True,
            header=_entry_header(entry),
        )
    changes = [
        _render_change(entry, sides, attname, audit_field, context)
        for attname, audit_field in _visible_fields(entry, sides)
    ]
    return RenderedEntry(
        entry=entry,
        changes=changes,
        balance_effect=_balance_effect(entry, sides, context),
        header=_entry_header(entry),
    )


def _balance_effect(
    entry: AuditLog,
    sides: Mapping[str, tuple[Any, Any]],
    context: _ReadContext,
) -> BalanceEffect | None:
    """Before → movement → after triplet for one account's balance change."""
    if entry.model_name != ACCOUNT_LABEL or 'balance' not in sides:
        return None
    old_raw, new_raw = sides['balance']
    if isinstance(old_raw, _Absent) or isinstance(new_raw, _Absent):
        return None
    try:
        old_value = Decimal(str(old_raw))
        new_value = Decimal(str(new_raw))
    except InvalidOperation:
        return None
    currency = context.currency_for(
        entry,
        sides,
        CurrencySource.SELF,
        old_side=False,
    )
    delta = new_value - old_value
    return BalanceEffect(
        account_name=entry.object_name or EMPTY,
        before=_format_money(old_value, currency),
        movement=_format_signed_money(delta, currency),
        after=_format_money(new_value, currency),
        negative=delta < 0,
    )


def _format_signed_money(value: Decimal, currency_code: str) -> str:
    formatted = _format_money(value, currency_code)
    return formatted if value < 0 else f'+{formatted}'


def _legacy_changes(diff: Mapping[str, Any]) -> list[RenderedChange]:
    """Print a pre-registry entry exactly as it was stored."""
    if 'created' in diff:
        return [
            RenderedChange(label=name, old=None, new=_as_text(value))
            for name, value in diff['created'].items()
        ]
    if 'deleted' in diff:
        return [
            RenderedChange(label=name, old=_as_text(value), new=None)
            for name, value in diff['deleted'].items()
        ]
    return [
        RenderedChange(
            label=name,
            old=_as_text(change.get('old')),
            new=_as_text(change.get('new')),
        )
        for name, change in diff.items()
        if isinstance(change, dict)
    ]


def _as_text(value: Any) -> str:
    return EMPTY if value is None or value == '' else str(value)


def _render_change(
    entry: AuditLog,
    sides: Mapping[str, tuple[Any, Any]],
    attname: str,
    audit_field: AuditField,
    context: _ReadContext,
) -> RenderedChange:
    old_raw, new_raw = sides[attname]
    return RenderedChange(
        label=str(audit_field.label),
        attname=attname,
        old=_render_side(
            entry,
            sides,
            attname,
            audit_field,
            old_raw,
            context,
            old_side=True,
        ),
        new=_render_side(
            entry,
            sides,
            attname,
            audit_field,
            new_raw,
            context,
            old_side=False,
        ),
    )


def _render_side(
    entry: AuditLog,
    sides: Mapping[str, tuple[Any, Any]],
    attname: str,
    audit_field: AuditField,
    value: Any,
    context: _ReadContext,
    *,
    old_side: bool,
) -> str | None:
    if isinstance(value, _Absent):
        return None
    if value is None or value == '':
        return EMPTY
    return _format_value(
        entry,
        sides,
        attname,
        audit_field,
        value,
        context,
        old_side=old_side,
    )


def _format_value(
    entry: AuditLog,
    sides: Mapping[str, tuple[Any, Any]],
    attname: str,
    audit_field: AuditField,
    value: Any,
    context: _ReadContext,
    *,
    old_side: bool,
) -> str:
    value_format = audit_field.format
    if value_format is Formatter.MONEY:
        currency = _money_currency(
            entry,
            sides,
            audit_field,
            context,
            old_side=old_side,
        )
        return _format_money(value, currency)
    if value_format is Formatter.FK:
        if audit_field.related is None:
            return _as_text(value)
        return context.related_name(audit_field.related, value)
    if value_format is Formatter.CHOICE:
        return _format_choice(entry.model_name, attname, audit_field, value)
    moment_format = _MOMENT_FORMATS.get(value_format)
    if moment_format is not None:
        return _format_moment(value, moment_format)
    return str(value)


def _money_currency(
    entry: AuditLog,
    sides: Mapping[str, tuple[Any, Any]],
    audit_field: AuditField,
    context: _ReadContext,
    *,
    old_side: bool,
) -> str:
    if audit_field.currency_from is None:
        return ''
    return context.currency_for(
        entry,
        sides,
        audit_field.currency_from,
        old_side=old_side,
    )


def _format_money(value: Any, currency_code: str) -> str:
    try:
        amount = Decimal(str(value)).quantize(_MONEY_EXPONENT)
    except (InvalidOperation, ValueError):
        return str(value)
    sign = '-' if amount < 0 else ''
    integral, _, fraction = f'{abs(amount):.2f}'.partition('.')
    grouped = f'{int(integral):,}'.replace(',', NBSP)
    printed = f'{sign}{grouped},{fraction}'
    return f'{printed}{NBSP}{currency_code}' if currency_code else printed


def _format_choice(
    model_label: str,
    attname: str,
    audit_field: AuditField,
    value: Any,
) -> str:
    labels = audit_field.choices or _model_choices(model_label, attname)
    label = labels.get(value)
    if label is None:
        return str(_('Код %(code)s') % {'code': value})
    return str(label)


def _model_choices(model_label: str, attname: str) -> dict[Any, str]:
    model: type[models.Model] = apps.get_model(model_label)
    model_field = model._meta.get_field(attname)
    choices = getattr(model_field, 'choices', None) or ()
    return {code: str(label) for code, label in choices}


def _format_moment(value: Any, moment_format: str) -> str:
    moment = _parse_moment(value)
    if moment is None:
        return str(value)
    if isinstance(moment, datetime) and timezone.is_aware(moment):
        moment = timezone.localtime(moment)
    return moment.strftime(moment_format)


def _parse_moment(value: Any) -> date | datetime | None:
    if isinstance(value, date | datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        pass
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None
