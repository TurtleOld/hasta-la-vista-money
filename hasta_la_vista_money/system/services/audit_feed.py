"""Assembles the audit history feed: operations, not raw entries.

An operation is the unit of a feed row. Entries carrying an
``operation_id`` group by it; older entries, written before the id
existed, group by a heuristic bucket of owner and second — and only after
the queryset is already scoped to one owner, per
:func:`hasta_la_vista_money.system.services.audit_context.audit_operation`.
Grouping and pagination both happen in SQL so an operation is never split
across a page boundary.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Protocol, cast

from django.db.models import Count, Max, QuerySet, Value
from django.db.models.fields import CharField
from django.db.models.functions import Cast, Coalesce, Concat, TruncSecond
from django.utils import timezone
from django.utils.translation import gettext as _gettext
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money.system.audit_registry import (
    ACCOUNT_LABEL,
    AUDIT_FIELDS,
    RECEIPT_LABEL,
    TRANSACTION_LABEL,
    TRANSFER_LABEL,
)
from hasta_la_vista_money.system.models import AuditLog, AuditOperationKind
from hasta_la_vista_money.system.services.audit_render import (
    EMPTY,
    BalanceEffect,
    RenderedChange,
    RenderedEntry,
    entry_has_visible_change,
    render_entries,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User


class _WithGroupKey(Protocol):
    """Shape of an ``AuditLog`` row after ``.annotate(group_key=...)``."""

    group_key: str


ARCHIVAL_BUCKET_LIMIT: Final = 12

# Priority order for the fallback rule applied to entries with no kind:
# pick the account name off the most senior model represented in the group.
_MODEL_PRIORITY: Final[tuple[str, ...]] = (
    TRANSFER_LABEL,
    RECEIPT_LABEL,
    TRANSACTION_LABEL,
    ACCOUNT_LABEL,
)

# Operations whose right-hand total must show the balance shift the edit
# caused, not the new value of the edited amount — the two only coincide by
# accident, and showing the shift unlabeled reads as the operation's amount.
_AMOUNT_EDIT_KINDS: Final = frozenset(
    {
        AuditOperationKind.TRANSACTION_EDIT,
        AuditOperationKind.RECEIPT_EDIT,
        AuditOperationKind.ACCOUNT_EDIT,
    },
)

_KIND_TITLES: Final[dict[str, Any]] = {
    AuditOperationKind.TRANSFER: _('Перевод'),
    AuditOperationKind.RECEIPT_PURCHASE: _('Чек'),
    AuditOperationKind.INCOME: _('Доход'),
    AuditOperationKind.EXPENSE: _('Расход'),
    AuditOperationKind.TRANSACTION_EDIT: _('Правка транзакции'),
    AuditOperationKind.TRANSACTION_DELETE: _('Удаление транзакции'),
    AuditOperationKind.RECEIPT_EDIT: _('Правка чека'),
    AuditOperationKind.RECEIPT_DELETE: _('Удаление чека'),
    AuditOperationKind.ACCOUNT_DELETE: _('Удаление счёта'),
    AuditOperationKind.STATEMENT_IMPORT: _('Импорт выписки'),
    AuditOperationKind.STATEMENT_IMPORT_RESOLUTION: _(
        'Разбор нерешённых строк',
    ),
}

# ACCOUNT_EDIT has no money effect of its own, so unlike a receipt or a
# transaction it gets no flat title: the changed field is named directly,
# and only when several fields change at once does it fall back to the
# generic "Изменение счёта «X»" from _fallback_title.
_ACCOUNT_EDIT_FIELD_TITLES: Final[dict[str, Any]] = {
    'name_account': _('Переименование счёта'),
    'type_account': _('Смена типа счёта'),
    'bank_id': _('Смена банка счёта'),
    'currency': _('Смена валюты счёта'),
    'balance': _('Корректировка остатка'),
    'limit_credit': _('Изменение кредитного лимита'),
    'payment_due_date': _('Изменение даты платежа'),
    'grace_period_days': _('Изменение льготного периода'),
    'archived_at': _('Архивация счёта'),
    'last_reconciled_at': _('Сверка счёта'),
}

# Fields the caption's participant slot names instead of listing them among
# "what changed" — their change is already spelled out there as an arrow.
_PARTICIPANT_FIELDS: Final[dict[str, frozenset[str]]] = {
    model_label: frozenset(
        attname
        for attname, audit_field in fields.items()
        if audit_field.participant
    )
    for model_label, fields in AUDIT_FIELDS.items()
}

_CAPTION_MODEL_FOR_KIND: Final[dict[AuditOperationKind, str]] = {
    AuditOperationKind.TRANSFER: TRANSFER_LABEL,
    AuditOperationKind.RECEIPT_PURCHASE: RECEIPT_LABEL,
    AuditOperationKind.INCOME: TRANSACTION_LABEL,
    AuditOperationKind.EXPENSE: TRANSACTION_LABEL,
    AuditOperationKind.TRANSACTION_EDIT: TRANSACTION_LABEL,
    AuditOperationKind.TRANSACTION_DELETE: TRANSACTION_LABEL,
    AuditOperationKind.RECEIPT_EDIT: RECEIPT_LABEL,
    AuditOperationKind.RECEIPT_DELETE: RECEIPT_LABEL,
    AuditOperationKind.ACCOUNT_EDIT: ACCOUNT_LABEL,
    AuditOperationKind.ACCOUNT_DELETE: ACCOUNT_LABEL,
}

# The measure slot's money field, by kind — absent for a kind whose right
# side already carries the operation's amount (an edit) or that has none.
_CAPTION_MONEY_FIELD: Final[dict[AuditOperationKind, str]] = {
    AuditOperationKind.TRANSFER: 'amount',
    AuditOperationKind.RECEIPT_PURCHASE: 'total_sum',
    AuditOperationKind.INCOME: 'amount',
    AuditOperationKind.EXPENSE: 'amount',
    AuditOperationKind.TRANSACTION_DELETE: 'amount',
    AuditOperationKind.RECEIPT_DELETE: 'total_sum',
}

# The one participant field whose current value is already captured, even
# when it did not change, by AuditLog.object_name — set by the write layer
# for exactly this purpose. A participant with no such fallback (a
# receipt's seller) simply drops out of the phrase when unchanged.
_OBJECT_NAME_FIELD: Final[dict[str, str]] = {
    ACCOUNT_LABEL: 'name_account',
    TRANSACTION_LABEL: 'account_id',
    RECEIPT_LABEL: 'account_id',
}

_CAPTION_FIELD_LIMIT: Final = 3


@dataclass(frozen=True)
class OperationTotal:
    """The operation's signed total, printed next to the time.

    ``negative`` is ``None`` for a transfer's total: it is the amount moved,
    not a gain or a loss, so it carries no sign color. ``is_shift`` marks a
    total that is a balance shift rather than the operation's own amount —
    true only for an edit of an amount field, where the two could otherwise
    be mistaken for each other.
    """

    amount: str
    negative: bool | None
    is_shift: bool


@dataclass(frozen=True)
class RenderedOperation:
    """One row of the audit feed: an operation, not a raw entry."""

    group_key: str
    title: str
    created_at: datetime
    archival: bool
    url_key: str = ''
    caption: str = ''
    entries: list[RenderedEntry] = field(default_factory=list)
    collapsed_count: int | None = None
    balance_chips: list[BalanceEffect] = field(default_factory=list)
    total: OperationTotal | None = None

    @property
    def has_changes(self) -> bool:
        if self.collapsed_count is not None:
            return True
        return any(entry.has_changes for entry in self.entries)


@dataclass(frozen=True)
class FeedPaginator:
    """Paginator-shaped summary of the whole feed, not just one page.

    ``count`` is the number of groups the SQL query found; a group later
    dropped by :meth:`RenderedOperation.has_changes` filtering (because
    none of its entries has a visible change) still counts here — an
    accepted approximation, since deciding that exactly would mean
    rendering every group on every page up front.
    """

    count: int
    num_pages: int


@dataclass(frozen=True)
class FeedPage:
    """One page of the audit feed, shaped like a Django ``Page``."""

    operations: list[RenderedOperation]
    number: int
    paginator: FeedPaginator
    has_previous: bool
    has_next: bool
    previous_page_number: int | None
    next_page_number: int | None


def _group_key_expression() -> Coalesce:
    return Coalesce(
        Cast('operation_id', output_field=CharField()),
        Concat(
            Cast('user_id', output_field=CharField()),
            Value('|'),
            Cast(TruncSecond('created_at'), output_field=CharField()),
            output_field=CharField(),
        ),
        output_field=CharField(),
    )


def list_operations(
    queryset: QuerySet[AuditLog],
    *,
    page: int,
    page_size: int,
) -> FeedPage:
    """Group ``queryset`` into operations and return one page of them.

    Grouping key and ordering are computed by the database; only the two
    queries needed to pick a page of groups and fetch their entries in
    full run here.
    """
    annotated = queryset.annotate(group_key=_group_key_expression())
    groups = (
        annotated.values('group_key')
        .annotate(
            latest_created=Max('created_at'),
            latest_id=Max('id'),
            size=Count('id'),
        )
        .order_by('-latest_created', '-latest_id')
    )
    total = groups.count()
    num_pages = max(1, -(-total // page_size)) if total else 1
    page_number = min(max(page, 1), num_pages)
    offset = (page_number - 1) * page_size
    page_groups = list(groups[offset : offset + page_size])

    operations: list[RenderedOperation] = []
    if page_groups:
        keys = [row['group_key'] for row in page_groups]
        sizes = {row['group_key']: row['size'] for row in page_groups}
        entries = list(
            annotated.filter(group_key__in=keys)
            .select_related('user')
            .order_by('-created_at', '-id'),
        )
        operations = _build_page_operations(entries, keys, sizes)

    return FeedPage(
        operations=operations,
        number=page_number,
        paginator=FeedPaginator(count=total, num_pages=num_pages),
        has_previous=page_number > 1,
        has_next=page_number < num_pages,
        previous_page_number=page_number - 1 if page_number > 1 else None,
        next_page_number=(page_number + 1 if page_number < num_pages else None),
    )


def _build_page_operations(
    entries: Sequence[AuditLog],
    keys: list[str],
    sizes: dict[str, int],
) -> list[RenderedOperation]:
    """Group fetched entries by their group key, then render each group.

    Groups whose rendered operation turns out empty (:attr:`RenderedOperation.
    has_changes` is ``False``) are dropped from the page.
    """
    by_key: dict[str, list[AuditLog]] = {}
    for entry in entries:
        key = cast('_WithGroupKey', entry).group_key
        by_key.setdefault(key, []).append(entry)
    return [
        operation
        for key in keys
        if (
            operation := _build_operation(key, by_key.get(key, []), sizes[key])
        ).has_changes
    ]


def _anchor_url_key(entries: list[AuditLog], archival: bool) -> str:
    """The operation's own address: an operation id, or an anchor's pk.

    A real operation is addressed by its ``operation_id``; an archival
    group has none, so it is addressed by the primary key of its anchor —
    the newest entry in the group, ``entries[0]`` under the feed's
    ``-created_at, -id`` ordering.
    """
    if not archival and entries[0].operation_id is not None:
        return str(entries[0].operation_id)
    return str(entries[0].pk)


def _build_operation(
    group_key: str,
    entries: list[AuditLog],
    size: int,
) -> RenderedOperation:
    if not entries:
        return RenderedOperation(
            group_key=group_key,
            title='',
            created_at=timezone.now(),
            archival=True,
        )
    archival = entries[0].operation_id is None
    created_at = entries[0].created_at
    if archival and size > ARCHIVAL_BUCKET_LIMIT:
        return _build_collapsed_operation(group_key, entries, created_at, size)
    return _render_full_operation(group_key, entries, archival, created_at)


def _render_full_operation(
    group_key: str,
    entries: list[AuditLog],
    archival: bool,
    created_at: datetime,
) -> RenderedOperation:
    """Render every entry of a group in full — no size-based collapsing.

    Shared by the feed (once the collapse check has already passed) and
    the operation screen, which always shows an operation whole regardless
    of how many entries an archival bucket happens to hold.
    """
    rendered = [item for item in render_entries(entries) if item.has_changes]
    # An archival group's composition is only a guess, so its balance chain
    # cannot be trusted either — it gets no chips, not even wrong ones.
    balance_chips = (
        []
        if archival
        else [
            item.balance_effect
            for item in rendered
            if item.balance_effect is not None
        ]
    )
    operation_kind = _operation_kind_of(entries)
    return RenderedOperation(
        group_key=group_key,
        title=_title_for(entries, rendered, operation_kind),
        created_at=created_at,
        archival=archival,
        url_key=_anchor_url_key(entries, archival),
        caption='' if archival else _caption_for(operation_kind, rendered),
        entries=rendered,
        balance_chips=balance_chips,
        total=_build_total(balance_chips, rendered, entries),
    )


def get_operation_detail(
    user: 'User',
    operation_key: str,
) -> RenderedOperation | None:
    """Look up one user's operation by its own address, rendered in full.

    ``operation_key`` is either an ``operation_id`` (a real operation) or
    the primary key of an archival group's anchor entry — the same two
    shapes :func:`_anchor_url_key` hands out. Anything outside the
    requesting user's own history, or matching neither shape, is reported
    as absent rather than raising, so the view can turn it into a 404.
    """
    try:
        key = uuid.UUID(operation_key)
    except ValueError:
        return _archival_operation_detail(user, operation_key)
    entries = list(
        AuditLog.objects.filter(user=user, operation_id=key)
        .select_related('user')
        .order_by('-created_at', '-id'),
    )
    if not entries:
        return None
    return _render_full_operation(
        str(key),
        entries,
        archival=False,
        created_at=entries[0].created_at,
    )


def _archival_operation_detail(
    user: 'User',
    operation_key: str,
) -> RenderedOperation | None:
    try:
        anchor_id = int(operation_key)
    except ValueError:
        return None
    anchor = AuditLog.objects.filter(
        user=user,
        pk=anchor_id,
        operation_id__isnull=True,
    ).first()
    if anchor is None:
        return None
    bucket_start = anchor.created_at.replace(microsecond=0)
    bucket_end = bucket_start + timedelta(seconds=1)
    entries = list(
        AuditLog.objects.filter(
            user=user,
            operation_id__isnull=True,
            created_at__gte=bucket_start,
            created_at__lt=bucket_end,
        )
        .select_related('user')
        .order_by('-created_at', '-id'),
    )
    return _render_full_operation(
        str(anchor_id),
        entries,
        archival=True,
        created_at=entries[0].created_at,
    )


def _operation_kind_of(entries: list[AuditLog]) -> AuditOperationKind | None:
    """The operation's kind, if any entry carries one and it's still known."""
    kind = next((entry.kind for entry in entries if entry.kind), None)
    if not kind:
        return None
    try:
        return AuditOperationKind(kind)
    except ValueError:
        return None


def _build_total(
    chips: list[BalanceEffect],
    rendered: list[RenderedEntry],
    entries: list[AuditLog],
) -> OperationTotal | None:
    if not chips:
        return None
    if len(chips) == 1:
        chip = chips[0]
        return OperationTotal(
            amount=chip.movement,
            negative=chip.negative,
            is_shift=_operation_kind_of(entries) in _AMOUNT_EDIT_KINDS,
        )
    transfer_amount = _find_transfer_amount(rendered)
    if transfer_amount is None:
        return None
    return OperationTotal(amount=transfer_amount, negative=None, is_shift=False)


def _find_transfer_amount(rendered: list[RenderedEntry]) -> str | None:
    amount_label = str(_('Сумма'))
    for item in rendered:
        if item.entry.model_name != TRANSFER_LABEL:
            continue
        for change in item.changes:
            if change.label == amount_label:
                return change.new or change.old
    return None


def _build_collapsed_operation(
    group_key: str,
    entries: list[AuditLog],
    created_at: datetime,
    size: int,
) -> RenderedOperation:
    """Summarize an archival bucket over the safety-valve limit.

    Checked with :func:`entry_has_visible_change` rather than
    :func:`render_entries`, so a bucket this large — an import, most
    likely — is never fully formatted just to be collapsed to one line.
    """
    if not any(entry_has_visible_change(entry) for entry in entries):
        return RenderedOperation(
            group_key=group_key,
            title='',
            created_at=created_at,
            archival=True,
        )
    title = _gettext('Массовое изменение · %(count)s записей') % {
        'count': size,
    }
    return RenderedOperation(
        group_key=group_key,
        title=title,
        created_at=created_at,
        archival=True,
        url_key=_anchor_url_key(entries, archival=True),
        collapsed_count=size,
    )


def _caption_for(
    operation_kind: AuditOperationKind | None,
    rendered: list[RenderedEntry],
) -> str:
    """The caption phrase: participants · what changed · measure.

    Read off the single entry the operation's kind is about — a transfer's
    two balance-chip account entries, say, are not it. An empty slot drops
    together with its separator.
    """
    if operation_kind is None:
        return ''
    model_label = _CAPTION_MODEL_FOR_KIND.get(operation_kind)
    if model_label is None:
        return ''
    item = next(
        (entry for entry in rendered if entry.entry.model_name == model_label),
        None,
    )
    if item is None:
        return ''
    slots = (
        _caption_participants(operation_kind, model_label, item),
        _caption_body(model_label, item.changes),
        _caption_measure(operation_kind, item.changes),
    )
    return ' · '.join(slot for slot in slots if slot)


def _caption_participants(
    operation_kind: AuditOperationKind,
    model_label: str,
    item: RenderedEntry,
) -> str:
    # A transfer's arrow means money moving between two accounts, always
    # printed in that order — a meaning kept apart from an edited value's
    # own arrow by never sharing a line with it (see module docstring).
    if operation_kind is AuditOperationKind.TRANSFER:
        by_attname = {change.attname: change for change in item.changes}
        from_change = by_attname.get('from_account_id')
        to_change = by_attname.get('to_account_id')
        from_name = from_change.new if from_change else EMPTY
        to_name = to_change.new if to_change else EMPTY
        return f'{from_name} → {to_name}'
    by_attname = {change.attname: change for change in item.changes}
    object_name_field = _OBJECT_NAME_FIELD.get(model_label)
    parts = []
    for attname, audit_field in AUDIT_FIELDS.get(model_label, {}).items():
        if not audit_field.participant:
            continue
        change = by_attname.get(attname)
        if change is not None:
            parts.append(_caption_side(change))
        elif attname == object_name_field and item.entry.object_name:
            parts.append(item.entry.object_name)
    return ' · '.join(part for part in parts if part)


def _caption_side(change: RenderedChange) -> str:
    if change.old is not None and change.new is not None:
        return f'{change.old} → {change.new}'
    return change.new or change.old or ''


def _caption_body(model_label: str, changes: list[RenderedChange]) -> str:
    participant_fields = _PARTICIPANT_FIELDS.get(model_label, frozenset())
    changed = [
        change
        for change in changes
        if change.attname not in participant_fields
        and change.old is not None
        and change.new is not None
    ]
    if not changed:
        return ''
    if len(changed) == 1:
        change = changed[0]
        return f'{change.old} → {change.new}'
    labels = [change.label for change in changed[:_CAPTION_FIELD_LIMIT]]
    text = ', '.join(labels)
    remaining = len(changed) - _CAPTION_FIELD_LIMIT
    if remaining > 0:
        text += str(_gettext(' и ещё %(count)s') % {'count': remaining})
    return text


def _caption_measure(
    operation_kind: AuditOperationKind,
    changes: list[RenderedChange],
) -> str:
    if operation_kind in _AMOUNT_EDIT_KINDS:
        return ''
    money_attname = _CAPTION_MONEY_FIELD.get(operation_kind)
    if money_attname is None:
        return ''
    for change in changes:
        if change.attname == money_attname:
            return change.new or change.old or ''
    return ''


def _title_for(
    entries: list[AuditLog],
    rendered: list[RenderedEntry],
    operation_kind: AuditOperationKind | None,
) -> str:
    if operation_kind is AuditOperationKind.ACCOUNT_EDIT:
        return _account_edit_title(entries, rendered)
    if operation_kind is not None:
        label = _KIND_TITLES.get(operation_kind)
        if label is not None:
            return str(label)
    return _fallback_title(entries)


def _account_edit_title(
    entries: list[AuditLog],
    rendered: list[RenderedEntry],
) -> str:
    account_item = next(
        (item for item in rendered if item.entry.model_name == ACCOUNT_LABEL),
        None,
    )
    if account_item is not None and len(account_item.changes) == 1:
        label = _ACCOUNT_EDIT_FIELD_TITLES.get(account_item.changes[0].attname)
        if label is not None:
            return str(label)
    return _fallback_title(entries)


def _fallback_title(entries: list[AuditLog]) -> str:
    by_model: dict[str, AuditLog] = {}
    for entry in entries:
        by_model.setdefault(entry.model_name, entry)
    name = ''
    for model_label in _MODEL_PRIORITY:
        candidate = by_model.get(model_label)
        if candidate is not None and candidate.object_name:
            name = candidate.object_name
            break
    return _gettext('Изменение счёта «%(name)s»') % {'name': name}
