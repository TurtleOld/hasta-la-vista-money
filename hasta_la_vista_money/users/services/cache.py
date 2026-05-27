import hashlib

from django.core.cache import cache

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
    cache.delete(get_reports_budget_charts_cache_key(user_id))
    cache.delete_many(
        [
            get_period_comparison_cache_key(user_id, period_type)
            for period_type in PERIOD_TYPES
        ],
    )
