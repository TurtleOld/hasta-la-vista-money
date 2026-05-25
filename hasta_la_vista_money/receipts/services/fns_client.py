"""HTTP client for the FNS mobile receipt API."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import httpx
import structlog
from django.conf import settings

from hasta_la_vista_money.receipts.services.fns_session_cache import (
    FNSSession,
    FNSSessionCache,
)

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable

HTTP_UNAUTHORIZED: Final[int] = 401
HTTP_FORBIDDEN: Final[int] = 403
HTTP_RATE_LIMIT: Final[int] = 429


class FNSIntegrationError(Exception):
    """Base exception for safe FNS integration failures."""


class FNSConfigurationError(FNSIntegrationError):
    """Raised when required FNS settings are missing."""


class FNSAuthenticationError(FNSIntegrationError):
    """Raised when FNS credentials are rejected."""


class FNSUnauthorizedError(FNSIntegrationError):
    """Raised when an existing FNS session is no longer valid."""


class FNSRateLimitError(FNSIntegrationError):
    """Raised when FNS rate-limits the family account."""


class FNSTemporaryUnavailableError(FNSIntegrationError):
    """Raised when the FNS API is temporarily unavailable."""


class FNSTimeoutError(FNSIntegrationError):
    """Raised when FNS ticket polling did not finish in time."""


class FNSMalformedResponseError(FNSIntegrationError):
    """Raised when FNS returns an unexpected JSON shape."""


@dataclass(frozen=True)
class FNSCredentials:
    """FNS mobile API credentials loaded from secret storage/env."""

    inn: str
    password: str
    client_secret: str


class FNSClient:
    """Fetch official receipt JSON from the FNS mobile API by QR string."""

    def __init__(
        self,
        *,
        session_cache: FNSSessionCache | None = None,
        http_client_factory: Callable[..., httpx.Client] = httpx.Client,
        base_url: str | None = None,
        credentials: FNSCredentials | None = None,
        timeout_seconds: float | None = None,
        poll_attempts: int | None = None,
        poll_interval_seconds: float | None = None,
    ) -> None:
        self._session_cache = session_cache or FNSSessionCache()
        self._http_client_factory = http_client_factory
        self._base_url = (base_url or settings.FNS_BASE_URL).rstrip('/')
        self._credentials = credentials or self._load_credentials()
        self._timeout_seconds = float(
            timeout_seconds
            if timeout_seconds is not None
            else settings.FNS_TIMEOUT_SECONDS,
        )
        self._poll_attempts = int(
            poll_attempts
            if poll_attempts is not None
            else settings.FNS_POLL_ATTEMPTS,
        )
        self._poll_interval_seconds = float(
            poll_interval_seconds
            if poll_interval_seconds is not None
            else settings.FNS_POLL_INTERVAL_SECONDS,
        )

    def fetch_receipt(self, qr_raw: str) -> dict[str, Any]:
        """Create/poll an FNS ticket and return the official receipt JSON."""
        session = self._session_cache.get() or self._authenticate()
        try:
            return self._fetch_receipt_with_session(session, qr_raw)
        except FNSUnauthorizedError:
            self._session_cache.clear()
            session = self._authenticate()
            return self._fetch_receipt_with_session(session, qr_raw)

    def _fetch_receipt_with_session(
        self,
        session: FNSSession,
        qr_raw: str,
    ) -> dict[str, Any]:
        ticket_id = self._create_ticket(session, qr_raw)
        return self._poll_ticket(session, ticket_id)

    def _authenticate(self) -> FNSSession:
        self._validate_credentials()
        payload = {
            'inn': self._credentials.inn,
            'password': self._credentials.password,
            'client_secret': self._credentials.client_secret,
        }
        logger.info('fns_auth_started')
        response_payload = self._request_json(
            'POST',
            '/mobile/users/lkfl/auth',
            json_payload=payload,
            auth_request=True,
        )
        session_id = _required_text(response_payload, 'sessionId')
        refresh_token = _optional_text(response_payload.get('refresh_token'))
        session = FNSSession(
            session_id=session_id,
            refresh_token=refresh_token,
        )
        self._session_cache.set(session)
        logger.info('fns_auth_succeeded')
        return session

    def _create_ticket(self, session: FNSSession, qr_raw: str) -> str:
        payload = self._request_json(
            'POST',
            '/ticket',
            json_payload={'qr': qr_raw},
            session=session,
        )
        ticket_id = _optional_text(payload.get('id')) or _optional_text(
            payload.get('ticketId'),
        )
        if ticket_id is None:
            raise FNSMalformedResponseError('FNS ticket id is missing')
        return ticket_id

    def _poll_ticket(
        self,
        session: FNSSession,
        ticket_id: str,
    ) -> dict[str, Any]:
        for attempt in range(self._poll_attempts):
            payload = self._request_json(
                'GET',
                f'/tickets/{ticket_id}',
                session=session,
            )
            receipt = _extract_receipt(payload)
            if receipt is not None:
                return payload
            if attempt < self._poll_attempts - 1:
                time.sleep(self._poll_interval_seconds)

        raise FNSTimeoutError('FNS ticket polling timed out')

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
        session: FNSSession | None = None,
        auth_request: bool = False,
    ) -> dict[str, Any]:
        headers = self._headers(session=session)
        try:
            with self._http_client_factory(
                timeout=self._timeout_seconds,
            ) as client:
                response = client.request(
                    method,
                    f'{self._base_url}{path}',
                    json=json_payload,
                    headers=headers,
                )
        except httpx.TimeoutException as exc:
            raise FNSTimeoutError('FNS request timed out') from exc
        except httpx.HTTPError as exc:
            raise FNSTemporaryUnavailableError('FNS request failed') from exc

        self._handle_status(response, auth_request=auth_request)

        try:
            payload = response.json()
        except ValueError as exc:
            raise FNSMalformedResponseError('FNS response is not JSON') from exc
        if not isinstance(payload, dict):
            raise FNSMalformedResponseError('FNS response is not an object')
        return payload

    def _handle_status(
        self,
        response: httpx.Response,
        *,
        auth_request: bool,
    ) -> None:
        if response.is_success:
            return
        if response.status_code == HTTP_RATE_LIMIT:
            raise FNSRateLimitError('FNS rate limit exceeded')
        if response.status_code in {HTTP_UNAUTHORIZED, HTTP_FORBIDDEN}:
            if auth_request:
                raise FNSAuthenticationError('FNS credentials rejected')
            raise FNSUnauthorizedError('FNS session is unauthorized')
        raise FNSTemporaryUnavailableError('FNS temporary error')

    def _headers(self, *, session: FNSSession | None) -> dict[str, str]:
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Device-Id': 'hasta-la-vista-money',
            'Device-OS': 'Android',
            'Version': '2',
            'clientVersion': '2.9.0',
        }
        if session is not None:
            headers['sessionId'] = session.session_id
        return headers

    def _load_credentials(self) -> FNSCredentials:
        return FNSCredentials(
            inn=str(settings.FNS_INN).strip(),
            password=str(settings.FNS_PASSWORD),
            client_secret=str(settings.FNS_CLIENT_SECRET),
        )

    def _validate_credentials(self) -> None:
        if not self._credentials.inn:
            raise FNSConfigurationError('FNS_INN is not configured')
        if not self._credentials.password:
            raise FNSConfigurationError('FNS_PASSWORD is not configured')
        if not self._credentials.client_secret:
            raise FNSConfigurationError('FNS_CLIENT_SECRET is not configured')


def _extract_receipt(payload: dict[str, Any]) -> dict[str, Any] | None:
    document = payload.get('document')
    if isinstance(document, dict):
        receipt = _as_dict(document.get('receipt'))
        if receipt is not None:
            return receipt
    ticket = payload.get('ticket')
    if isinstance(ticket, dict):
        document = ticket.get('document')
        if isinstance(document, dict):
            receipt = _as_dict(document.get('receipt'))
            if receipt is not None:
                return receipt
    receipt = _as_dict(payload.get('receipt'))
    if receipt is not None:
        return receipt
    return None


def _required_text(payload: dict[str, Any], field: str) -> str:
    text = _optional_text(payload.get(field))
    if text is None:
        message = f'FNS field is missing: {field}'
        raise FNSMalformedResponseError(message)
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_dict(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): item for key, item in value.items()}


__all__ = [
    'FNSAuthenticationError',
    'FNSClient',
    'FNSConfigurationError',
    'FNSCredentials',
    'FNSIntegrationError',
    'FNSMalformedResponseError',
    'FNSRateLimitError',
    'FNSTemporaryUnavailableError',
    'FNSTimeoutError',
    'FNSUnauthorizedError',
]
