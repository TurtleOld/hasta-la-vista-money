"""Calendar-day reads that keep an explicit bank day.

A movement may carry ``bank_calendar_date``: the bank day is known even
though the datetime column only holds a technical anchor. Calendar reads
must use that day. A legacy movement without the field keeps the local
date of its moment, exactly as before.
"""

from datetime import date, datetime
from typing import Any

from django.db.models import (
    DateField,
    DateTimeField,
    Expression,
    F,
    QuerySet,
)
from django.db.models.functions import Cast, Coalesce, TruncDate, TruncMonth
from django.utils import timezone

CALENDAR_DAY_ALIAS = '_calendar_day'


def calendar_day(field: str = 'date') -> Expression:
    """Return the calendar day of a movement as a ``DateField``."""
    return Coalesce(
        F('bank_calendar_date'),
        TruncDate(field),
        output_field=DateField(),
    )


def calendar_month(field: str = 'date') -> Expression:
    """Return the calendar month as the datetime key callers expect."""
    return Cast(
        TruncMonth(calendar_day(field)),
        output_field=DateTimeField(),
    )


def local_calendar_date(value: date | datetime) -> date:
    """Return the local calendar date of a date or an aware moment."""
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            return value.date()
        return timezone.localtime(value).date()
    return value


def movement_calendar_date(
    moment: date | datetime,
    bank_calendar_date: date | None,
) -> date:
    """Return the explicit bank day, else the legacy local day."""
    if bank_calendar_date is not None:
        return bank_calendar_date
    return local_calendar_date(moment)


def filter_calendar_range[QuerySetType: QuerySet[Any, Any]](
    queryset: QuerySetType,
    start: date | datetime,
    end: date | datetime,
    *,
    field: str = 'date',
) -> QuerySetType:
    """Keep rows whose calendar day is inside the inclusive range."""
    return queryset.alias(
        **{CALENDAR_DAY_ALIAS: calendar_day(field)},
    ).filter(
        **{
            f'{CALENDAR_DAY_ALIAS}__range': (
                local_calendar_date(start),
                local_calendar_date(end),
            ),
        },
    )


def filter_calendar_from[QuerySetType: QuerySet[Any, Any]](
    queryset: QuerySetType,
    start: date | datetime,
    *,
    field: str = 'date',
) -> QuerySetType:
    """Keep rows whose calendar day is on or after ``start``."""
    return queryset.alias(
        **{CALENDAR_DAY_ALIAS: calendar_day(field)},
    ).filter(
        **{f'{CALENDAR_DAY_ALIAS}__gte': local_calendar_date(start)},
    )


def filter_calendar_to[QuerySetType: QuerySet[Any, Any]](
    queryset: QuerySetType,
    end: date | datetime,
    *,
    field: str = 'date',
) -> QuerySetType:
    """Keep rows whose calendar day is on or before ``end``."""
    return queryset.alias(
        **{CALENDAR_DAY_ALIAS: calendar_day(field)},
    ).filter(
        **{f'{CALENDAR_DAY_ALIAS}__lte': local_calendar_date(end)},
    )
