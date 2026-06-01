"""Throttling classes for API rate limiting.

This module provides throttling classes for controlling API request rates,
including login rate limiting to prevent brute force attacks.
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from rest_framework.throttling import (
    AnonRateThrottle,
    UserRateThrottle,
)


class LoginRateThrottle(UserRateThrottle):
    """Throttle for login attempts.

    Limits the rate of login attempts per authenticated user
    to prevent brute force attacks.
    """

    scope = 'login'

    def get_rate(self) -> str | None:
        """Return login throttle rate from project REST settings."""
        rate = self.THROTTLE_RATES.get(self.scope)
        if rate:
            return rate

        throttle_rates = settings.REST_FRAMEWORK.get(
            'DEFAULT_THROTTLE_RATES',
            {},
        )
        try:
            return throttle_rates[self.scope]
        except KeyError as exc:
            msg = f"No default throttle rate set for '{self.scope}' scope"
            raise ImproperlyConfigured(msg) from exc


class AnonLoginRateThrottle(AnonRateThrottle):
    """Throttle for anonymous login attempts.

    Limits the rate of login attempts for anonymous users
    to prevent brute force attacks.
    """

    scope = 'anon'
