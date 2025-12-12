"""Throttling classes for API rate limiting.

This module provides throttling classes for controlling API request rates,
including login rate limiting to prevent brute force attacks.
"""

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


class AnonLoginRateThrottle(AnonRateThrottle):
    """Throttle for anonymous login attempts.

    Limits the rate of login attempts for anonymous users
    to prevent brute force attacks.
    """

    scope = 'anon'
