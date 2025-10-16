from rest_framework.throttling import UserRateThrottle


class LoginRateThrottle(UserRateThrottle):
    scope = 'login'


class AnonLoginRateThrottle(UserRateThrottle):
    scope = 'anon_login'
    
    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            return None  # Don't throttle authenticated users
        return super().get_cache_key(request, view)
