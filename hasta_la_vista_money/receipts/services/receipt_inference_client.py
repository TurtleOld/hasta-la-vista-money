"""HTTP client for the internal receipt inference service."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import structlog
from decouple import config
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money.receipts.services.ai_providers import (
    ModelUnavailableError,
    RateLimitExceededError,
)

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile

logger = structlog.get_logger(__name__)

HTTP_RATE_LIMIT = 429
HTTP_CONNECT_TIMEOUT = 10.0
HTTP_WRITE_TIMEOUT = 60.0
HTTP_POOL_TIMEOUT = 60.0


def get_receipt_inference_url() -> str:
    """Return the configured receipt inference base URL."""
    return str(config('RECEIPT_INFERENCE_URL', default='')).strip().rstrip('/')


def should_use_receipt_inference() -> bool:
    """Check whether the internal receipt inference service is configured."""
    return bool(get_receipt_inference_url())


class ReceiptInferenceClient:
    """Client for the internal receipt inference HTTP API."""

    def __init__(self) -> None:
        self._base_url = get_receipt_inference_url()
        self._timeout = config(
            'RECEIPT_INFERENCE_TIMEOUT',
            default=420.0,
            cast=float,
        )

    def _build_timeout(self) -> httpx.Timeout:
        """Use an extended read timeout for long-running inference."""
        return httpx.Timeout(
            connect=HTTP_CONNECT_TIMEOUT,
            read=self._timeout,
            write=HTTP_WRITE_TIMEOUT,
            pool=HTTP_POOL_TIMEOUT,
        )

    def _parse_error_response(self, response: httpx.Response) -> str:
        """Extract error details from a non-success response."""
        try:
            payload = response.json()
        except ValueError:
            return response.text
        if isinstance(payload, dict):
            return str(payload.get('message', response.text))
        return response.text

    def _handle_error_response(self, response: httpx.Response) -> None:
        """Map inference-service errors to existing receipt exceptions."""
        error_message = self._parse_error_response(response)

        if response.status_code == HTTP_RATE_LIMIT:
            raise RateLimitExceededError(
                str(_('Превышен лимит запросов к сервису распознавания.')),
            )

        if response.status_code in {404, 503}:
            raise ModelUnavailableError(
                str(
                    _(
                        'Сервис распознавания чеков недоступен. '
                        'Проверьте настройки receipt inference.',
                    ),
                ),
            )

        raise RuntimeError(
            str(
                _(
                    f'Ошибка сервиса распознавания чеков '
                    f'(HTTP {response.status_code}): {error_message}',
                ),
            ),
        )

    def _validate_payload(self, payload: dict[str, Any]) -> str:
        """Validate successful payload and return raw JSON string."""
        if not payload.get('success'):
            error_code = str(payload.get('error_code', 'unknown_error'))
            message = str(
                payload.get(
                    'message',
                    _('Сервис распознавания чеков вернул ошибку.'),
                ),
            )

            if error_code == 'model_unavailable':
                raise ModelUnavailableError(message)
            if error_code == 'rate_limit_exceeded':
                raise RateLimitExceededError(message)

            raise RuntimeError(message)

        data = payload.get('data')
        if not isinstance(data, dict):
            raise RuntimeError(
                str(_('Сервис распознавания чеков вернул некорректный JSON.')),
            )

        return json.dumps(data, ensure_ascii=False)

    def analyze(self, uploaded_file: UploadedFile) -> str:
        """Upload a receipt image and return normalized receipt JSON."""
        if not self._base_url:
            raise RuntimeError('RECEIPT_INFERENCE_URL is not configured')

        uploaded_file.seek(0)
        file_bytes = uploaded_file.read()
        files = {
            'file': (
                uploaded_file.name,
                file_bytes,
                getattr(
                    uploaded_file,
                    'content_type',
                    'application/octet-stream',
                ),
            ),
        }

        logger.info(
            'receipt_inference_request_started',
            base_url=self._base_url,
            file_name=uploaded_file.name,
            file_size=len(file_bytes),
            timeout=self._timeout,
        )

        try:
            with httpx.Client(timeout=self._build_timeout()) as client:
                response = client.post(
                    f'{self._base_url}/v1/receipt/parse',
                    files=files,
                )

            if not response.is_success:
                self._handle_error_response(response)

            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError(
                    str(
                        _(
                            'Сервис распознавания чеков '
                            'вернул неожиданный ответ.',
                        ),
                    ),
                )

            return self._validate_payload(payload)
        except (ModelUnavailableError, RateLimitExceededError):
            raise
        except httpx.TimeoutException as exc:
            logger.warning(
                'receipt_inference_timeout',
                base_url=self._base_url,
                timeout=self._timeout,
                exc_info=True,
            )
            raise RuntimeError(
                str(
                    _(
                        'Превышено время ожидания ответа сервиса '
                        'распознавания чеков.',
                    ),
                ),
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning(
                'receipt_inference_http_error',
                base_url=self._base_url,
                error=str(exc),
                exc_info=True,
            )
            raise RuntimeError(
                str(
                    _(
                        'Не удалось связаться с сервисом распознавания чеков.',
                    ),
                ),
            ) from exc


def analyze_image_with_receipt_inference(uploaded_file: UploadedFile) -> str:
    """Analyze a receipt image via the internal receipt inference service."""
    client = ReceiptInferenceClient()
    return client.analyze(uploaded_file)
