"""Date contract shared by every movement written from a statement row."""

from datetime import UTC, date, datetime

from django.utils import timezone

from hasta_la_vista_money.users.models import BankStatementRow


def statement_row_calendar_date(row: BankStatementRow) -> date:
    """Return the row's bank day, else the legacy local date of its moment."""
    if row.bank_calendar_date is not None:
        return row.bank_calendar_date
    if row.transaction_date is None:
        raise ValueError('row')
    return timezone.localtime(row.transaction_date).date()


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
        raise ValueError('row')
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
