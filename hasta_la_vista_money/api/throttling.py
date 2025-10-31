from rest_framework.throttling import (
    AnonRateThrottle,
    UserRateThrottle,
)


class LoginRateThrottle(UserRateThrottle):
    scope = 'login'


class AnonLoginRateThrottle(AnonRateThrottle):
    scope = 'anon'
