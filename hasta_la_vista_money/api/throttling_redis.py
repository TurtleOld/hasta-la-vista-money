"""
Redis-based throttling classes for API rate limiting.

These classes extend Django REST Framework's built-in throttling to use
Redis cache backend for improved performance and scalability in production.
"""

from typing import Any

from django.http import HttpRequest
from rest_framework.throttling import (
    AnonRateThrottle,
    SimpleRateThrottle,
    UserRateThrottle,
)


class RedisAnonRateThrottle(AnonRateThrottle):
    """
    Throttle for anonymous users using Redis cache.

    Uses Django's cache framework which is configured to use Redis
    in production environments.
    """

    cache_format = 'throttle_%(scope)s_%(ident)s'


class RedisUserRateThrottle(UserRateThrottle):
    """
    Throttle for authenticated users using Redis cache.

    Uses Django's cache framework which is configured to use Redis
    in production environments.
    """

    cache_format = 'throttle_%(scope)s_%(ident)s'


class RedisLoginRateThrottle(SimpleRateThrottle):
    """
    Throttle for login attempts using Redis cache.

    Limits the rate of login attempts to prevent brute force attacks.
    Uses Redis for distributed rate limiting across multiple servers.
    """

    scope = 'login'
    cache_format = 'throttle_%(scope)s_%(ident)s'

    def get_cache_key(
        self,
        request: HttpRequest,
        view: Any,
    ) -> str | None:
        """
        Generate cache key for login throttling.

        Args:
            request: HTTP request object
            view: View being accessed

        Returns:
            Cache key string or None
        """
        if request.user.is_authenticated:
            user_pk = request.user.pk
            if user_pk is None:
                return None
            ident: int | str = user_pk
        else:
            ident_value = self.get_ident(request)  # type: ignore[arg-type]
            if ident_value is None:
                return None
            ident = ident_value

        return self.cache_format % {
            'scope': self.scope,
            'ident': ident,
        }
