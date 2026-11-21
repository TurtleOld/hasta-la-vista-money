"""Date contract shared by every movement written from a statement row."""

from datetime import UTC, date, datetime

from hasta_la_vista_money.core.calendar_days import movement_calendar_date
from hasta_la_vista_money.users.models import BankStatementRow

#: Raised when a row that must carry a date has none. Programmer error, not
#: a user-facing message.
NO_ROW_DATE = 'statement row has no operation date'


def statement_row_day(row: BankStatementRow) -> date | None:
    """Return the row's bank day, else the legacy local date of its moment.

    The single place that decides which calendar day a row belongs to. Callers
    that must have a date use :func:`statement_row_calendar_date`.
    """
    moment = row.transaction_date
    if moment is None:
        return None
    return movement_calendar_date(moment, row.bank_calendar_date)


def statement_row_calendar_date(row: BankStatementRow) -> date:
    """Return the row's bank day, else the legacy local date of its moment."""
    day = statement_row_day(row)
    if day is None:
        raise ValueError(NO_ROW_DATE)
    return day


def statement_row_bank_day(row: BankStatementRow) -> date | None:
    """Return only a proved bank calendar day, never a datetime date part.

    A row with real datetime precision has no proved bank day: a datetime is a
    technical anchor, not the bank's own calendar day.
    """
    if row.date_precision == BankStatementRow.DatePrecision.DATETIME:
        return None
    return row.bank_calendar_date


def statement_row_movement_date(
    row: BankStatementRow,
) -> tuple[datetime, date | None]:
    """Return the movement moment and the bank day stored with it.

    A known bank day is a technical UTC midnight anchor, not the bank's
    time. A row with real datetime precision keeps its original moment and
    is never marked as day-only. A legacy row without a bank day keeps its
    original moment exactly.
    """
    moment = row.transaction_date
    if moment is None:
        raise ValueError(NO_ROW_DATE)
    if row.date_precision == BankStatementRow.DatePrecision.DATETIME:
        return moment, None
    if row.bank_calendar_date is not None:
        return (
            datetime.combine(
                row.bank_calendar_date,
                datetime.min.time(),
                tzinfo=UTC,
            ),
            row.bank_calendar_date,
        )
    return moment, None
