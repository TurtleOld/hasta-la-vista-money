from django.core.cache import cache


def get_user_detailed_statistics_cache_key(user_id: int) -> str:
    """Return cache key for detailed dashboard statistics."""
    return f'user_stats_{user_id}'


def invalidate_user_detailed_statistics_cache(user_id: int) -> None:
    """Invalidate cached detailed dashboard statistics for a user."""
    cache.delete(get_user_detailed_statistics_cache_key(user_id))
