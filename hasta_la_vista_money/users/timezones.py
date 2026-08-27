"""Shared access to the canonical list of IANA timezone identifiers."""

from functools import lru_cache
from zoneinfo import available_timezones


@lru_cache(maxsize=1)
def get_available_timezones() -> tuple[str, ...]:
    """Return the sorted list of IANA timezone identifiers.

    Cached because ``zoneinfo.available_timezones()`` scans the tz
    database on every call.
    """
    return tuple(sorted(available_timezones()))
