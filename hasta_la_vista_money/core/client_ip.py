from django.conf import settings
from django.http import HttpRequest


def get_client_ip(request: HttpRequest) -> str | None:
    """Return the client IP address behind ``TRUSTED_PROXY_COUNT`` proxies.

    Mirrors DRF ``NUM_PROXIES``: the address appended by the nearest trusted
    proxy is used, so entries a client prepends to X-Forwarded-For are ignored.
    """
    remote_addr: str | None = request.META.get('REMOTE_ADDR')
    proxy_count: int = settings.TRUSTED_PROXY_COUNT
    forwarded_for: str | None = request.META.get('HTTP_X_FORWARDED_FOR')
    if proxy_count <= 0 or not forwarded_for:
        return remote_addr
    addresses = forwarded_for.split(',')
    return addresses[-min(proxy_count, len(addresses))].strip()
