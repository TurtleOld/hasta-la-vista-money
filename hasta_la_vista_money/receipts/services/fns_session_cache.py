"""Django cache storage for FNS mobile API sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from django.conf import settings
from django.core.cache import cache

FNS_SESSION_CACHE_KEY: Final[str] = 'receipts:fns:session'


@dataclass(frozen=True)
class FNSSession:
    """Authenticated FNS mobile API session."""

    session_id: str
    refresh_token: str | None = None


class FNSSessionCache:
    """Persist FNS session tokens in Django cache only."""

    def get(self) -> FNSSession | None:
        """Return cached FNS session, if present and well-formed."""
        payload = cache.get(FNS_SESSION_CACHE_KEY)
        if not isinstance(payload, dict):
            return None

        session_id = payload.get('session_id')
        if not isinstance(session_id, str) or not session_id.strip():
            return None

        refresh_token = payload.get('refresh_token')
        return FNSSession(
            session_id=session_id,
            refresh_token=(
                refresh_token
                if isinstance(refresh_token, str) and refresh_token
                else None
            ),
        )

    def set(self, session: FNSSession) -> None:
        """Store FNS session with configured TTL."""
        ttl = int(getattr(settings, 'FNS_SESSION_CACHE_TTL_SECONDS', 3600))
        payload: dict[str, Any] = {
            'session_id': session.session_id,
            'refresh_token': session.refresh_token,
        }
        cache.set(FNS_SESSION_CACHE_KEY, payload, timeout=ttl)

    def clear(self) -> None:
        """Drop cached FNS session."""
        cache.delete(FNS_SESSION_CACHE_KEY)


__all__ = ['FNS_SESSION_CACHE_KEY', 'FNSSession', 'FNSSessionCache']
