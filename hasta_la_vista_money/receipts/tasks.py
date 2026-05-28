"""Celery tasks for background receipt processing.

The view layer only enqueues ``process_pending_receipt`` after persisting the
PendingReceipt + uploaded image. All inference, parsing and state transitions
live here so the work survives the user closing the page.
"""

from datetime import timedelta
from typing import Any

import structlog
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.utils import timezone
from django.utils.translation import gettext as _

from hasta_la_vista_money.receipts.models import (
    PendingReceipt,
    PendingReceiptStatus,
)
from hasta_la_vista_money.receipts.repositories import ReceiptRepository
from hasta_la_vista_money.receipts.repositories.seller_repository import (
    SellerRepository,
)
from hasta_la_vista_money.receipts.services.category_classifier import (
    ReceiptItemCategoryService,
)
from hasta_la_vista_money.receipts.services.fns_client import (
    FNSAuthenticationError,
    FNSClient,
    FNSConfigurationError,
    FNSIntegrationError,
    FNSMalformedResponseError,
    FNSRateLimitError,
    FNSTemporaryUnavailableError,
    FNSTimeoutError,
)
from hasta_la_vista_money.receipts.services.fns_mapper import (
    FNSReceiptMappingError,
    map_fns_receipt_to_receipt_data,
)
from hasta_la_vista_money.receipts.services.fns_qr import (
    QRCodeDecodeError,
    QRCodeExtractor,
    QRCodeNotFoundError,
)
from hasta_la_vista_money.receipts.services.pending_receipt_service import (
    PendingReceiptService,
)
from hasta_la_vista_money.receipts.services.ai_providers import (
    ModelUnavailableError,
    RateLimitExceededError,
)
from hasta_la_vista_money.receipts.validators.parsed_receipt import (
    ReceiptParseValidationError,
    validate_receipt_parse_payload,
)

logger = structlog.get_logger(__name__)

_PROCESSING_GRACE_MINUTES = 10
_RATE_LIMIT_MESSAGE = _(
    'Сервис распознавания перегружен запросами. '
    'Попробуйте ещё раз через несколько минут.',
)
_MODEL_UNAVAILABLE_MESSAGE = _(
    'Сервис распознавания временно недоступен. '
    'Попробуйте ещё раз через несколько минут.',
)
_TIMEOUT_MESSAGE = _(
    'Распознавание заняло слишком много времени и было прервано. '
    'Попробуйте ещё раз или загрузите более чёткое фото меньшего размера.',
)
_PARSE_FAILED_MESSAGE = _(
    'Не удалось разобрать данные чека из ФНС. '
    'Попробуйте загрузить более чёткое фото.',
)
_UNEXPECTED_MESSAGE = _(
    'Произошла непредвиденная ошибка при обработке чека. Попробуйте ещё раз.',
)
_NO_QR_MESSAGE = _(
    'Не удалось найти QR-код на изображении чека. '
    'Загрузите более чёткое фото, где QR-код виден полностью.',
)
_BAD_QR_MESSAGE = _(
    'QR-код на изображении не похож на QR-код кассового чека ФНС. '
    'Проверьте фото и загрузите чек заново.',
)
_FNS_UNAVAILABLE_MESSAGE = _(
    'Сервис ФНС временно недоступен. Попробуйте обработать чек позже.',
)
_FNS_RATE_LIMIT_MESSAGE = _(
    'Сервис ФНС временно ограничил частоту запросов. '
    'Попробуйте обработать чек через несколько минут.',
)
_FNS_AUTH_MESSAGE = _(
    'Не удалось авторизоваться в ФНС. Проверьте настройки интеграции.',
)
_MISSING_FILE_MESSAGE = _(
    'Файл изображения чека не найден. Загрузите чек заново.',
)
_TIMEOUT_RECOVERY_MESSAGE = _(
    'Обработка прервана по таймауту. Попробуйте ещё раз.',
)
_FAILURE_RULES = (
    (
        RateLimitExceededError,
        'pending_receipt_rate_limited',
        _RATE_LIMIT_MESSAGE,
    ),
    (
        (ModelUnavailableError, ConnectionError),
        'pending_receipt_model_unavailable',
        _MODEL_UNAVAILABLE_MESSAGE,
    ),
    (QRCodeNotFoundError, 'pending_receipt_qr_not_found', _NO_QR_MESSAGE),
    (QRCodeDecodeError, 'pending_receipt_qr_decode_failed', _BAD_QR_MESSAGE),
    (
        FNSRateLimitError,
        'pending_receipt_fns_rate_limited',
        _FNS_RATE_LIMIT_MESSAGE,
    ),
    (
        (FNSAuthenticationError, FNSConfigurationError),
        'pending_receipt_fns_auth_failed',
        _FNS_AUTH_MESSAGE,
    ),
    (
        (FNSTemporaryUnavailableError, FNSTimeoutError),
        'pending_receipt_fns_unavailable',
        _FNS_UNAVAILABLE_MESSAGE,
    ),
    (
        (FNSMalformedResponseError, FNSReceiptMappingError),
        'pending_receipt_fns_parse_failed',
        _PARSE_FAILED_MESSAGE,
    ),
    (
        FNSIntegrationError,
        'pending_receipt_fns_failed',
        _FNS_UNAVAILABLE_MESSAGE,
    ),
    (
        (SoftTimeLimitExceeded, TimeoutError),
        'pending_receipt_timed_out',
        _TIMEOUT_MESSAGE,
    ),
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


def _run_fns_pipeline(pending: PendingReceipt) -> dict[str, Any]:
    """Process a pending receipt through QR -> FNS -> mapper pipeline."""
    with pending.image_file.open('rb') as image_fp:
        qr_data = QRCodeExtractor().extract(image_fp)

    fns_payload = FNSClient().fetch_receipt(qr_data.raw)
    receipt_data = map_fns_receipt_to_receipt_data(fns_payload)
    receipt_data['items'] = ReceiptItemCategoryService().categorize_items(
        user=pending.user,
        items=receipt_data.get('items', []),
    )

    inn = receipt_data.get('inn')
    if inn and not receipt_data.get('retail_place'):
        seller = SellerRepository().find_by_inn(user=pending.user, inn=inn)
        if seller and seller.retail_place not in (None, '', 'Нет данных'):
            receipt_data['retail_place'] = seller.retail_place

    validated = validate_receipt_parse_payload(receipt_data).to_dict()
    validated['_fns_raw'] = fns_payload
    return validated


def _run_processing_pipeline(pending: PendingReceipt) -> dict[str, Any]:
    """Run the FNS receipt processing pipeline."""
    return _run_fns_pipeline(pending)


def _classify_failure(exc: Exception) -> tuple[str, str]:
    """Map an exception to a (log_event, user-facing message) pair.

    ``ReceiptParseValidationError`` may carry a Russian ``user_message`` with
    a specific, actionable explanation (sum mismatch, missing items, etc.).
    When present, it overrides the generic parse-failed fallback.
    """
    for exception_types, event, message in _FAILURE_RULES:
        if isinstance(exc, exception_types):
            return event, str(message)
    if isinstance(exc, ReceiptParseValidationError) and exc.user_message:
        return 'pending_receipt_parse_failed', exc.user_message
    if isinstance(exc, json.JSONDecodeError | ValueError | TypeError):
        return 'pending_receipt_parse_failed', str(_PARSE_FAILED_MESSAGE)
    return 'pending_receipt_failed', str(_UNEXPECTED_MESSAGE)


@shared_task(  # type: ignore[untyped-decorator]
    bind=True,
    name='receipts.process_pending_receipt',
    autoretry_for=(ConnectionError,),
    max_retries=2,
    retry_backoff=True,
    acks_late=True,
)
def process_pending_receipt(_self: Any, pending_receipt_id: int) -> None:
    """Run inference for a pending receipt and update its state.

    Loads the persisted image, calls ``analyze_image_with_ai`` (which uses the
    local receipt inference service), parses the result and transitions the
    PendingReceipt to ``ready`` or ``failed``.

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
        receipt_data = _run_processing_pipeline(pending)
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


@shared_task(name='receipts.cleanup_stale_pending_receipts')  # type: ignore[untyped-decorator]
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
