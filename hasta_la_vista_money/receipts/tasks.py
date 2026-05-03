"""Celery tasks for background receipt processing.

The view layer only enqueues ``process_pending_receipt`` after persisting the
PendingReceipt + uploaded image. All inference, parsing and state transitions
live here so the work survives the user closing the page.
"""

import json
import re
from datetime import timedelta
from typing import Any

import structlog
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _

from hasta_la_vista_money.receipts.models import (
    PendingReceipt,
    PendingReceiptStatus,
)
from hasta_la_vista_money.receipts.repositories import ReceiptRepository
from hasta_la_vista_money.receipts.services import analyze_image_with_ai
from hasta_la_vista_money.receipts.services.pending_receipt_service import (
    PendingReceiptService,
)
from hasta_la_vista_money.receipts.services.receipt_ai_prompt import (
    ModelUnavailableError,
    RateLimitExceededError,
)

logger = structlog.get_logger(__name__)

_PROCESSING_GRACE_MINUTES = 10
_RATE_LIMIT_MESSAGE = _('Превышен лимит запросов к сервису распознавания')
_MODEL_UNAVAILABLE_MESSAGE = _('Сервис распознавания временно недоступен')
_TIMEOUT_MESSAGE = _('Истёк лимит времени обработки чека')
_PARSE_FAILED_MESSAGE = _('Не удалось разобрать ответ распознавания')
_UNEXPECTED_MESSAGE = _('Непредвиденная ошибка при распознавании чека')
_MISSING_FILE_MESSAGE = _('Файл изображения отсутствует')
_TIMEOUT_RECOVERY_MESSAGE = _(
    'Обработка прервана по таймауту. Попробуйте ещё раз.',
)


def _build_service() -> PendingReceiptService:
    """Construct PendingReceiptService outside the DI container.

    Celery workers run without a Django request, so the runtime container is
    unavailable. The background flow only needs ``mark_ready``/``mark_failed``
    and ``delete_with_file``, none of which touch ``ReceiptCreatorService`` —
    so we pass ``None`` for it. Conversion to a final Receipt happens later
    in the request-bound ReviewPendingReceiptView, where the container is
    available.
    """
    return PendingReceiptService(
        receipt_creator_service=None,  # type: ignore[arg-type]
        receipt_repository=ReceiptRepository(),
    )


_JSON_CODE_BLOCK_RE = re.compile(r'```(?:json)?\s*({.*?})\s*```', re.DOTALL)


def _parse_inference_payload(raw: str) -> dict[str, Any]:
    """Parse inference response into a dict, stripping markdown fences.

    Args:
        raw: JSON string returned by ``analyze_image_with_ai`` (possibly
            wrapped in a Markdown code fence).

    Returns:
        Parsed receipt dictionary.

    Raises:
        ValueError: When the payload is empty.
        json.JSONDecodeError: When the payload is not valid JSON.
    """
    if not raw:
        raise ValueError('Empty inference response')
    match = _JSON_CODE_BLOCK_RE.search(raw)
    cleaned = match.group(1) if match else raw.strip()
    return json.loads(cleaned)


def _run_inference(pending: PendingReceipt) -> dict[str, Any]:
    """Open the stored image and run the configured inference backend."""
    with pending.image_file.open('rb') as image_fp:
        raw = analyze_image_with_ai(image_fp, user_id=pending.user_id)
    return _parse_inference_payload(raw)


def _classify_failure(exc: Exception) -> tuple[str, str]:
    """Map an exception to a (log_event, user-facing message) pair."""
    if isinstance(exc, RateLimitExceededError):
        return 'pending_receipt_rate_limited', str(_RATE_LIMIT_MESSAGE)
    if isinstance(exc, ModelUnavailableError):
        return 'pending_receipt_model_unavailable', str(
            _MODEL_UNAVAILABLE_MESSAGE,
        )
    if isinstance(exc, SoftTimeLimitExceeded):
        return 'pending_receipt_timed_out', str(_TIMEOUT_MESSAGE)
    if isinstance(exc, json.JSONDecodeError | ValueError | TypeError):
        return 'pending_receipt_parse_failed', str(_PARSE_FAILED_MESSAGE)
    return 'pending_receipt_failed', str(_UNEXPECTED_MESSAGE)


@shared_task(
    bind=True,
    name='receipts.process_pending_receipt',
    autoretry_for=(ConnectionError, TimeoutError),
    max_retries=2,
    retry_backoff=True,
    acks_late=True,
)
def process_pending_receipt(_self: Any, pending_receipt_id: int) -> None:
    """Run inference for a pending receipt and update its state.

    Loads the persisted image, calls ``analyze_image_with_ai`` (which routes
    to the local PaddleOCR-VL service or the AI fallback), parses the result
    and transitions the PendingReceipt to ``ready`` or ``failed``.

    Args:
        _self: Bound Celery task instance (unused, present for ``bind=True``).
        pending_receipt_id: Primary key of the PendingReceipt to process.
    """
    try:
        pending = PendingReceipt.objects.select_related('user').get(
            pk=pending_receipt_id,
        )
    except PendingReceipt.DoesNotExist:
        logger.warning(
            'pending_receipt_missing',
            pending_receipt_id=pending_receipt_id,
        )
        return

    service = _build_service()

    if not pending.image_file:
        service.mark_failed(
            pending_receipt=pending,
            error_message=str(_MISSING_FILE_MESSAGE),
        )
        return

    try:
        receipt_data = _run_inference(pending)
    except Exception as exc:
        event, message = _classify_failure(exc)
        service.mark_failed(
            pending_receipt=pending,
            error_message=message,
        )
        logger.warning(
            event,
            pending_receipt_id=pending_receipt_id,
            error=str(exc),
        )
        return

    service.mark_ready(
        pending_receipt=pending,
        receipt_data=receipt_data,
    )


@shared_task(name='receipts.cleanup_stale_pending_receipts')
def cleanup_stale_pending_receipts() -> dict[str, int]:
    """Recover stuck processing rows and purge expired pending receipts.

    Marks ``processing`` rows older than the Celery hard time limit (with a
    safety margin) as ``failed`` so the user can retry. Deletes all rows past
    their ``expires_at``, removing the on-disk image alongside the row.

    Returns:
        Dict with counts of recovered and purged rows for logging.
    """
    service = _build_service()
    now = timezone.now()
    hard_limit_seconds = int(
        getattr(settings, 'CELERY_TASK_TIME_LIMIT', 30 * 60),
    )
    stuck_threshold = now - timedelta(
        seconds=hard_limit_seconds + _PROCESSING_GRACE_MINUTES * 60,
    )

    recovered = 0
    stuck = PendingReceipt.objects.filter(
        status=PendingReceiptStatus.PROCESSING,
        created_at__lt=stuck_threshold,
    )
    for pending in stuck:
        service.mark_failed(
            pending_receipt=pending,
            error_message=str(_TIMEOUT_RECOVERY_MESSAGE),
        )
        recovered += 1

    purged = 0
    expired = PendingReceipt.objects.filter(expires_at__lt=now)
    for pending in expired:
        service.delete_with_file(pending_receipt=pending)
        purged += 1

    logger.info(
        'pending_receipt_cleanup',
        recovered=recovered,
        purged=purged,
    )
    return {'recovered': recovered, 'purged': purged}
