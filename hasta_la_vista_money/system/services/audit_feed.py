"""Assembles the audit history feed: operations, not raw entries.

An operation is the unit of a feed row. Entries carrying an
``operation_id`` group by it; older entries, written before the id
existed, group by a heuristic bucket of owner and second — and only after
the queryset is already scoped to one owner, per
:func:`hasta_la_vista_money.system.services.audit_context.audit_operation`.
Grouping and pagination both happen in SQL so an operation is never split
across a page boundary.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Protocol, cast

from django.db.models import Count, Max, QuerySet, Value
from django.db.models.fields import CharField
from django.db.models.functions import Cast, Coalesce, Concat, TruncSecond
from django.utils import timezone
from django.utils.translation import gettext as _gettext
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money.system.audit_registry import (
    ACCOUNT_LABEL,
    RECEIPT_LABEL,
    TRANSACTION_LABEL,
    TRANSFER_LABEL,
)
from hasta_la_vista_money.system.models import AuditLog, AuditOperationKind
from hasta_la_vista_money.system.services.audit_render import (
    BalanceEffect,
    RenderedEntry,
    entry_has_visible_change,
    render_entries,
)


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
    AuditOperationKind.ACCOUNT_EDIT: _('Правка счёта'),
    AuditOperationKind.ACCOUNT_DELETE: _('Удаление счёта'),
    AuditOperationKind.STATEMENT_IMPORT: _('Импорт выписки'),
    AuditOperationKind.STATEMENT_IMPORT_RESOLUTION: _(
        'Разбор нерешённых строк',
    ),
}


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
    return RenderedOperation(
        group_key=group_key,
        title=_title_for(entries),
        created_at=created_at,
        archival=archival,
        entries=rendered,
        balance_chips=balance_chips,
        total=_build_total(balance_chips, rendered, entries),
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
        collapsed_count=size,
    )


def _title_for(entries: list[AuditLog]) -> str:
    operation_kind = _operation_kind_of(entries)
    if operation_kind is not None:
        label = _KIND_TITLES.get(operation_kind)
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
