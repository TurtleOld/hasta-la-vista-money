from typing import TypedDict

from django.templatetags.static import static
from django.urls import reverse

from hasta_la_vista_money import __version__

PRECACHE_STATIC_PATHS: tuple[str, ...] = (
    'css/styles.min.css',
    'css/swipe-list.css',
    'css/driver.css',
    'js/dist/app.js',
    'js/htmx.min.js',
    'js/alpine.csp.min.js',
    'manifest.webmanifest',
    'img/pwa/icon-192.png',
    'img/pwa/apple-touch-icon.png',
    'img/favicon/favicon.ico',
)


class PwaPrecachePayload(TypedDict):
    version: str
    offline_url: str
    precache: list[str]


def get_pwa_precache_payload() -> PwaPrecachePayload:
    offline_url = reverse('offline')
    precache = [offline_url, *[static(path) for path in PRECACHE_STATIC_PATHS]]
    return {
        'version': __version__,
        'offline_url': offline_url,
        'precache': precache,
    }
