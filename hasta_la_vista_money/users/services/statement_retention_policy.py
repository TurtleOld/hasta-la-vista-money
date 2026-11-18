"""When statement bank details are still available or due for cleanup.

This is retention policy, not model state: the row owns the deadline fields,
while the upload is the fallback for rows created before per-row deadlines.
"""

from datetime import datetime, timedelta

from django.utils import timezone

from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    User,
)


def statement_retention_deadline(
    user: User,
    now: datetime | None = None,
) -> datetime:
    """Return the deadline for a newly uploaded statement."""
    return (now or timezone.now()) + timedelta(
        days=user.statement_retention_days,
    )


def upload_generation_due(
    upload: BankStatementUpload,
    now: datetime | None = None,
) -> bool:
    """Tell whether the upload's PDF and bank sums are due for cleanup."""
    return upload.retention_cleaned_at is None and upload.expires_at <= (
        now or timezone.now()
    )


def row_data_due(
    row: BankStatementRow,
    *,
    upload_due: bool,
    now: datetime | None = None,
) -> bool:
    """Tell whether this row's bank details are due for cleanup.

    An explicit row deadline wins over the upload generation. A row without
    one follows the upload only while that generation is still uncleaned, so
    legacy cleaned rows do not silently get a new deadline.
    """
    if row.data_cleaned_at is not None:
        return False
    moment = now or timezone.now()
    if row.data_expires_at is not None:
        return row.data_expires_at <= moment
    return upload_due


def row_has_bank_data(
    row: BankStatementRow,
    now: datetime | None = None,
) -> bool:
    """Tell whether the row's bank details are still stored."""
    if row.data_cleaned_at is not None:
        return False
    moment = now or timezone.now()
    if row.data_expires_at is not None:
        return row.data_expires_at > moment
    upload = row.upload
    return upload.retention_cleaned_at is None and upload.expires_at > moment
