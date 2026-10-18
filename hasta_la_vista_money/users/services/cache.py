import hashlib
import time
from typing import cast

from django.core.cache import cache

from hasta_la_vista_money.users.models import FamilyGroupMembership


def _user_statistics_version_key(user_id: int) -> str:
    return f'user_stats_version_{user_id}'


def _user_statistics_version(user_id: int) -> int:
    # Fresh timestamp after expiry or eviction never revives old cache keys.
    return cast(
        'int',
        cache.get_or_set(
            _user_statistics_version_key(user_id),
            time.time_ns,
            timeout=None,
        ),
    )


def get_user_detailed_statistics_cache_key(
    user_id: int,
    suffix: str = 'default',
) -> str:
    """Return cache key for detailed dashboard statistics."""
    version = _user_statistics_version(user_id)
    suffix_hash = hashlib.sha256(suffix.encode()).hexdigest()[:16]
    return f'user_stats_{user_id}_{version}_{suffix_hash}'


def get_dashboard_summary_cache_key(user_id: int, currency: str) -> str:
    """Return cache key for dashboard summary data."""
    version = _user_statistics_version(user_id)
    return f'user_dashboard_summary_{user_id}_{version}_{currency}'


def get_period_comparison_cache_key(
    user_id: int,
    period_type: str,
    currency: str,
) -> str:
    """Return cache key for cached period comparison data."""
    version = _user_statistics_version(user_id)
    return (
        f'user_period_comparison_{user_id}_{version}_{period_type}_{currency}'
    )


def invalidate_user_detailed_statistics_cache(user_id: int) -> None:
    """Invalidate cached dashboard and statistics data for a user."""
    cache.set(
        _user_statistics_version_key(user_id),
        time.time_ns(),
        timeout=None,
    )


def invalidate_group_statistics_cache(
    group_id: int,
    *user_ids: int,
) -> None:
    """Invalidate cached statistics of the group members and extra users."""
    member_ids = FamilyGroupMembership.objects.filter(
        group_id=group_id,
    ).values_list('user_id', flat=True)
    for user_id in {*member_ids, *user_ids}:
        invalidate_user_detailed_statistics_cache(user_id)


def invalidate_user_circle_statistics_cache(user_id: int) -> None:
    """Invalidate cached statistics of the user and all their group peers."""
    peer_ids = FamilyGroupMembership.objects.filter(
        group_id__in=FamilyGroupMembership.objects.filter(
            user_id=user_id,
        ).values('group_id'),
    ).values_list('user_id', flat=True)
    for peer_id in {*peer_ids, user_id}:
        invalidate_user_detailed_statistics_cache(peer_id)
