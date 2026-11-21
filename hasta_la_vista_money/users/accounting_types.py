"""Immutable DTOs of the unified accounting problem service.

The service reads statements and returns these types; it never depends on
templates, requests or the rendering layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date
    from decimal import Decimal


class ProblemKind(StrEnum):
    """Every known accounting problem shown in the unified section."""

    DEFERRED = 'deferred'
    INCOMPLETE_MARKUP = 'incomplete_markup'
    UNRESOLVED = 'unresolved'
    PROBABLE_DUPLICATE = 'probable_duplicate'
    REPAYMENT = 'repayment'
    PARSE_ERROR = 'parse_error'
    UPLOAD_FAILED = 'upload_failed'
    RECOVERY = 'recovery'
    BALANCE_ATTENTION = 'balance_attention'


class ProblemAction(StrEnum):
    """Existing screen that resolves a problem; the view builds the URL."""

    MARKUP = 'markup'
    RECONCILE = 'reconcile'
    ACCOUNTS = 'accounts'
    UPLOAD = 'upload'


class ProblemState(StrEnum):
    """Data state of a problem, independent of its decision."""

    ALL = 'all'
    AVAILABLE = 'available'
    RECOVERY = 'recovery'


@dataclass(frozen=True)
class AccountingProblemFilter:
    """Filters that do not depend on the current request."""

    bank_code: str = ''
    currency: str = ''
    kind: str = ''
    state: str = ProblemState.ALL


@dataclass(frozen=True)
class AccountingProblemItem:
    """One problem row or one aggregated upload-level problem."""

    kind: str
    action: str
    upload_id: int
    row_id: int | None
    account_id: int
    account_name: str
    bank_code: str
    bank_name: str
    currency: str
    transaction_date: date | None
    date_known: bool
    amount: Decimal | None
    amount_known: bool
    description: str
    reason: str
    row_count: int
    data_available: bool
    direction: str = ''


@dataclass(frozen=True)
class AccountingProblemCounts:
    """Badge-compatible counters: one source object contributes once."""

    total_items: int
    by_kind: Mapping[str, int]
    recovery_row_count: int
    excluded_row_count: int
    unresolved_row_count: int


@dataclass(frozen=True)
class AccountingAccountOption:
    """An owner's account available in the filter."""

    id: int
    name: str
    bank_code: str
    bank_name: str
    currency: str


@dataclass(frozen=True)
class AccountingKnownTotal:
    """Known unposted amount of one currency and direction."""

    currency: str
    direction: str
    amount: Decimal
    row_count: int


@dataclass(frozen=True)
class AccountingProblemList:
    """A request-independent snapshot of every current problem."""

    items: tuple[AccountingProblemItem, ...]
    counts: AccountingProblemCounts
    accounts: tuple[AccountingAccountOption, ...]
    totals: tuple[AccountingKnownTotal, ...]
    totals_incomplete: bool
    excluded_reasons: tuple[tuple[str, int], ...]
    incomplete_reasons: tuple[str, ...]


def frozen_counts(
    *,
    total_items: int,
    by_kind: dict[str, int],
    recovery_row_count: int,
    excluded_row_count: int,
    unresolved_row_count: int,
) -> AccountingProblemCounts:
    """Build counters with a read-only per-kind mapping."""
    return AccountingProblemCounts(
        total_items=total_items,
        by_kind=MappingProxyType(dict(by_kind)),
        recovery_row_count=recovery_row_count,
        excluded_row_count=excluded_row_count,
        unresolved_row_count=unresolved_row_count,
    )
