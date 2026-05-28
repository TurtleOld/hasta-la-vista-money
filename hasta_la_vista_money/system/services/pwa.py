import hashlib
from pathlib import Path
from typing import TypedDict

from django.contrib.staticfiles import finders
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


def _build_precache_version(static_paths: tuple[str, ...]) -> str:
    hasher = hashlib.sha256()
    hasher.update(__version__.encode())

    for static_path in static_paths:
        hasher.update(static_path.encode())
        resolved_path = finders.find(static_path)
        if not resolved_path:
            hasher.update(b'missing')
            continue

        try:
            hasher.update(Path(resolved_path).read_bytes())
        except OSError:
            hasher.update(str(Path(resolved_path).stat().st_mtime_ns).encode())

    return f'{__version__}-{hasher.hexdigest()[:12]}'


def get_pwa_precache_payload() -> PwaPrecachePayload:
    offline_url = reverse('offline')
    precache = [offline_url, *[static(path) for path in PRECACHE_STATIC_PATHS]]
    return {
        'version': _build_precache_version(PRECACHE_STATIC_PATHS),
        'offline_url': offline_url,
        'precache': precache,
    }
