import hashlib

from django.core.cache import cache

from hasta_la_vista_money import constants
from hasta_la_vista_money.users.models import FamilyGroupMembership

PERIOD_TYPES = ('month', 'quarter', 'year')


def _user_statistics_version_key(user_id: int) -> str:
    return f'user_stats_version_{user_id}'


def get_user_detailed_statistics_cache_key(
    user_id: int,
    suffix: str = 'default',
) -> str:
    """Return cache key for detailed dashboard statistics."""
    version = cache.get(_user_statistics_version_key(user_id), 1)
    suffix_hash = hashlib.sha256(suffix.encode()).hexdigest()[:16]
    return f'user_stats_{user_id}_{version}_{suffix_hash}'


def get_dashboard_summary_cache_key(user_id: int) -> str:
    """Return cache key for dashboard summary data."""
    return f'user_dashboard_summary_{user_id}'


def get_period_comparison_cache_key(user_id: int, period_type: str) -> str:
    """Return cache key for cached period comparison data."""
    return f'user_period_comparison_{user_id}_{period_type}'


def get_reports_budget_charts_cache_key(user_id: int) -> str:
    """Return cache key for cached reports budget charts."""
    return f'user_reports_budget_charts_{user_id}'


def invalidate_user_detailed_statistics_cache(user_id: int) -> None:
    """Invalidate cached dashboard and reports data for a user."""
    version_key = _user_statistics_version_key(user_id)
    cache.set(version_key, int(cache.get(version_key, 1)) + 1)
    cache.delete(get_dashboard_summary_cache_key(user_id))
    reports_key = get_reports_budget_charts_cache_key(user_id)
    cache.delete_many(
        [
            reports_key,
            *(
                f'{reports_key}:{period}'
                for period in constants.REPORTS_BUDGET_CHART_PERIODS
            ),
        ],
    )
    cache.delete_many(
        [
            get_period_comparison_cache_key(user_id, period_type)
            for period_type in PERIOD_TYPES
        ],
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
