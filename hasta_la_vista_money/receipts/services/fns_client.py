"""HTTP client for the FNS mobile receipt API."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import httpx
import structlog
from django.conf import settings

from hasta_la_vista_money import constants
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
        started_at = time.monotonic()
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
            self._log_request_exception(
                event='fns_http_timeout',
                method=method,
                path=path,
                auth_request=auth_request,
                started_at=started_at,
                error=exc,
            )
            raise FNSTimeoutError('FNS request timed out') from exc
        except httpx.HTTPError as exc:
            self._log_request_exception(
                event='fns_http_transport_error',
                method=method,
                path=path,
                auth_request=auth_request,
                started_at=started_at,
                error=exc,
            )
            raise FNSTemporaryUnavailableError('FNS request failed') from exc

        if not response.is_success:
            self._log_failed_response(
                response=response,
                method=method,
                path=path,
                auth_request=auth_request,
                session=session,
                started_at=started_at,
            )
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

    def _log_request_exception(
        self,
        *,
        event: str,
        method: str,
        path: str,
        auth_request: bool,
        started_at: float,
        error: httpx.HTTPError,
    ) -> None:
        logger.warning(
            event,
            method=method.upper(),
            endpoint=f'{self._base_url}{path}',
            failure_stage=_failure_stage(auth_request),
            duration_ms=_duration_ms(started_at),
            timeout_seconds=self._timeout_seconds,
            exception_type=type(error).__name__,
            error=str(error),
        )

    def _log_failed_response(
        self,
        *,
        response: httpx.Response,
        method: str,
        path: str,
        auth_request: bool,
        session: FNSSession | None,
        started_at: float,
    ) -> None:
        response_type, response_keys, diagnostics, excerpt = (
            self._safe_response_details(response=response, session=session)
        )
        response_headers = {
            name: value
            for name in constants.FNS_DIAGNOSTIC_RESPONSE_HEADERS
            if (value := response.headers.get(name)) is not None
        }
        context: dict[str, Any] = {
            'method': method.upper(),
            'endpoint': f'{self._base_url}{path}',
            'failure_stage': _failure_stage(auth_request),
            'failure_category': _failure_category(
                response=response,
                auth_request=auth_request,
            ),
            'status_code': response.status_code,
            'reason_phrase': response.reason_phrase,
            'duration_ms': _duration_ms(started_at),
            'content_type': response.headers.get('content-type', ''),
            'response_body_bytes': len(response.content),
            'response_type': response_type,
        }
        if response_headers:
            context['response_headers'] = response_headers
        if response_keys:
            context['response_json_keys'] = response_keys
        if diagnostics:
            context['response_diagnostics'] = diagnostics
        if excerpt:
            context['response_excerpt'] = excerpt
        logger.warning('fns_http_request_failed', **context)

    def _safe_response_details(
        self,
        *,
        response: httpx.Response,
        session: FNSSession | None,
    ) -> tuple[str, list[str] | None, dict[str, object] | None, str | None]:
        try:
            payload = response.json()
        except ValueError:
            excerpt = self._redact_text(response.text, session=session)
            return 'text', None, None, excerpt

        if not isinstance(payload, dict):
            return type(payload).__name__, None, None, None
        response_keys = sorted(str(key) for key in payload)
        diagnostics = self._diagnostic_payload(payload, session=session)
        return 'json_object', response_keys, diagnostics or None, None

    def _diagnostic_payload(
        self,
        payload: dict[Any, Any],
        *,
        session: FNSSession | None,
    ) -> dict[str, object]:
        diagnostics: dict[str, object] = {}
        for raw_key, value in payload.items():
            key = str(raw_key)
            normalized_key = key.replace('_', '').replace('-', '').lower()
            if normalized_key not in constants.FNS_DIAGNOSTIC_FIELDS:
                continue
            diagnostics[key] = self._diagnostic_value(
                value,
                session=session,
            )
        return diagnostics

    def _diagnostic_value(
        self,
        value: Any,
        *,
        session: FNSSession | None,
    ) -> object:
        if isinstance(value, dict):
            return self._diagnostic_payload(value, session=session)
        if isinstance(value, list):
            return [
                self._diagnostic_value(item, session=session)
                for item in value[: constants.FNS_DIAGNOSTIC_LIST_ITEM_LIMIT]
            ]
        if isinstance(value, str):
            return self._redact_text(value, session=session)
        if value is None or isinstance(value, bool | int | float):
            return value
        return self._redact_text(
            json.dumps(value, ensure_ascii=False, default=str),
            session=session,
        )

    def _redact_text(
        self,
        text: str,
        *,
        session: FNSSession | None,
    ) -> str:
        redacted = ' '.join(text.split())
        sensitive_values = [
            self._credentials.inn,
            self._credentials.password,
            self._credentials.client_secret,
        ]
        if session is not None:
            sensitive_values.extend(
                [session.session_id, session.refresh_token or ''],
            )
        for value in sensitive_values:
            if value:
                redacted = redacted.replace(
                    value,
                    constants.FNS_REDACTED_VALUE,
                )
        return redacted[: constants.FNS_DIAGNOSTIC_BODY_MAX_LENGTH]

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


def _duration_ms(started_at: float) -> int:
    return round((time.monotonic() - started_at) * 1000)


def _failure_stage(auth_request: bool) -> str:
    return 'authentication' if auth_request else 'receipt_fetch'


def _failure_category(
    *,
    response: httpx.Response,
    auth_request: bool,
) -> str:
    if response.status_code == HTTP_RATE_LIMIT:
        return 'rate_limited'
    if auth_request and response.status_code in {
        HTTP_UNAUTHORIZED,
        HTTP_FORBIDDEN,
    }:
        return 'authentication_rejected'
    if auth_request and response.is_server_error:
        return 'authentication_endpoint_error'
    if response.is_server_error:
        return 'remote_server_error'
    return 'unexpected_http_status'


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
