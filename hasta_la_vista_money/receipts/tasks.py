"""Celery tasks for background receipt processing.

The view layer enqueues processing-log jobs after persisting their source
data. All inference, parsing and state transitions live here so the work
survives the user closing the page.
"""

import json
from datetime import timedelta
from typing import Any, cast

import httpx
import structlog
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _

from config.containers import ApplicationContainer
from core.repositories.protocols import ProductRepositoryProtocol
from hasta_la_vista_money import constants
from hasta_la_vista_money.receipts.models import (
    ProductCategory,
    ReceiptProcessingLog,
    ReceiptProcessingStatus,
)
from hasta_la_vista_money.receipts.protocols.services import (
    CategoryMergeProposalServiceProtocol,
    CategoryTwinDetectionServiceProtocol,
    ExternalProductCategoryServiceProtocol,
)
from hasta_la_vista_money.receipts.repositories.seller_repository import (
    SellerRepository,
)
from hasta_la_vista_money.receipts.services.ai_providers import (
    ModelUnavailableError,
    RateLimitExceededError,
)
from hasta_la_vista_money.receipts.services.category_classifier import (
    ReceiptItemCategoryService,
)
from hasta_la_vista_money.receipts.services.category_twin_detection import (
    CategoryTwinDetectionError,
)
from hasta_la_vista_money.receipts.services.external_category import (
    ExternalCategoryResponseError,
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
    parse_fns_qr,
)
from hasta_la_vista_money.receipts.services.receipt_processing_service import (
    ReceiptProcessingService,
)
from hasta_la_vista_money.receipts.validators.parsed_receipt import (
    ReceiptParseValidationError,
    validate_receipt_parse_payload,
)
from hasta_la_vista_money.users.models import User

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
        'receipt_processing_rate_limited',
        _RATE_LIMIT_MESSAGE,
    ),
    (
        (ModelUnavailableError, ConnectionError),
        'receipt_processing_model_unavailable',
        _MODEL_UNAVAILABLE_MESSAGE,
    ),
    (QRCodeNotFoundError, 'receipt_processing_qr_not_found', _NO_QR_MESSAGE),
    (QRCodeDecodeError, 'receipt_processing_qr_decode_failed', _BAD_QR_MESSAGE),
    (
        FNSRateLimitError,
        'receipt_processing_fns_rate_limited',
        _FNS_RATE_LIMIT_MESSAGE,
    ),
    (
        (FNSAuthenticationError, FNSConfigurationError),
        'receipt_processing_fns_auth_failed',
        _FNS_AUTH_MESSAGE,
    ),
    (
        (FNSTemporaryUnavailableError, FNSTimeoutError),
        'receipt_processing_fns_unavailable',
        _FNS_UNAVAILABLE_MESSAGE,
    ),
    (
        (FNSMalformedResponseError, FNSReceiptMappingError),
        'receipt_processing_fns_parse_failed',
        _PARSE_FAILED_MESSAGE,
    ),
    (
        FNSIntegrationError,
        'receipt_processing_fns_failed',
        _FNS_UNAVAILABLE_MESSAGE,
    ),
    (
        (SoftTimeLimitExceeded, TimeoutError),
        'receipt_processing_timed_out',
        _TIMEOUT_MESSAGE,
    ),
)


def _get_receipt_item_category_service() -> ReceiptItemCategoryService:
    """Resolve ReceiptItemCategoryService through the DI container."""
    return cast(
        'ReceiptItemCategoryService',
        ApplicationContainer().receipts.receipt_item_category_service(),
    )


def _get_external_product_category_service() -> (
    ExternalProductCategoryServiceProtocol
):
    """Resolve the optional external product-category fallback."""
    return cast(
        'ExternalProductCategoryServiceProtocol',
        ApplicationContainer().receipts.external_product_category_service(),
    )


def _get_category_twin_detection_service() -> (
    CategoryTwinDetectionServiceProtocol
):
    """Resolve the optional twin-category detection service."""
    return cast(
        'CategoryTwinDetectionServiceProtocol',
        ApplicationContainer().receipts.category_twin_detection_service(),
    )


def _get_category_merge_proposal_service() -> (
    CategoryMergeProposalServiceProtocol
):
    """Resolve the twin-category merge proposal service."""
    return cast(
        'CategoryMergeProposalServiceProtocol',
        ApplicationContainer().receipts.category_merge_proposal_service(),
    )


def _get_product_repository() -> ProductRepositoryProtocol:
    """Resolve the product repository through the DI container."""
    return cast(
        'ProductRepositoryProtocol',
        ApplicationContainer().receipts.product_repository(),
    )


def _run_fns_pipeline_from_raw(
    log: ReceiptProcessingLog,
    raw_qr: str,
) -> dict[str, Any]:
    """Run the FNS lookup -> mapper -> validate tail from a decoded QR string.

    Shared by the photo-upload pipeline (which extracts ``raw_qr`` from the
    image first) and the browser-camera-scan pipeline (which already has
    the decoded string and skips extraction entirely).
    """
    fns_payload = FNSClient().fetch_receipt(raw_qr)
    receipt_data = map_fns_receipt_to_receipt_data(fns_payload)
    receipt_data['items'] = (
        _get_receipt_item_category_service().categorize_items(
            user=log.user,
            items=receipt_data.get('items', []),
        )
    )

    inn = receipt_data.get('inn')
    if inn and not receipt_data.get('retail_place'):
        seller = SellerRepository().find_by_inn(user=log.user, inn=inn)
        if seller and seller.retail_place not in (None, '', 'Нет данных'):
            receipt_data['retail_place'] = seller.retail_place

    validated = validate_receipt_parse_payload(receipt_data).to_dict()
    validated['_fns_raw'] = fns_payload
    return validated


def _get_receipt_processing_service() -> ReceiptProcessingService:
    return cast(
        'ReceiptProcessingService',
        ApplicationContainer().receipts.receipt_processing_service(),
    )


def _run_processing_log_pipeline(
    log: ReceiptProcessingLog,
    service: ReceiptProcessingService,
    task_id: str,
) -> dict[str, Any] | None:
    """Fetch and validate FNS data after claiming the fiscal identity."""
    raw_qr = log.qr_raw
    if not raw_qr:
        if not log.image_file:
            raise ValueError(str(_MISSING_FILE_MESSAGE))
        with log.image_file.open('rb') as image_fp:
            qr_data = QRCodeExtractor().extract(image_fp)
        raw_qr = qr_data.raw
        fiscal_key = qr_data.fiscal_key
    else:
        fiscal_key = log.fiscal_key or parse_fns_qr(raw_qr).fiscal_key
    if not service.claim_fiscal_key(
        log=log,
        fiscal_key=fiscal_key,
        task_id=task_id,
    ):
        return None
    return _run_fns_pipeline_from_raw(log, raw_qr)


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
        return 'receipt_processing_parse_failed', exc.user_message
    if isinstance(exc, json.JSONDecodeError | ValueError | TypeError):
        return 'receipt_processing_parse_failed', str(_PARSE_FAILED_MESSAGE)
    return 'receipt_processing_failed', str(_UNEXPECTED_MESSAGE)


@shared_task(  # type: ignore[untyped-decorator]
    bind=True,
    name='receipts.process_receipt_processing_log',
    autoretry_for=(ConnectionError,),
    max_retries=2,
    retry_backoff=True,
    acks_late=True,
)
def process_receipt_processing_log(
    self: Any,
    processing_log_id: int,
) -> None:
    """Create a final receipt directly after a successful FNS lookup."""
    try:
        log = ReceiptProcessingLog.objects.select_related(
            'user',
            'account',
        ).get(
            pk=processing_log_id,
        )
    except ReceiptProcessingLog.DoesNotExist:
        logger.warning(
            'receipt_processing_log_missing',
            log_id=processing_log_id,
        )
        return
    if log.status != ReceiptProcessingStatus.PROCESSING:
        return

    service = _get_receipt_processing_service()
    task_id = str(self.request.id)
    try:
        receipt_data = _run_processing_log_pipeline(log, service, task_id)
        if receipt_data is None:
            return
        service.complete(
            log=log,
            receipt_data=receipt_data,
            task_id=task_id,
        )
    except Exception as exc:
        event, message = _classify_failure(exc)
        service.mark_failed(log=log, error_message=message, task_id=task_id)
        logger.warning(
            event,
            processing_log_id=processing_log_id,
            error=str(exc),
        )


@shared_task(  # type: ignore[untyped-decorator]
    name=constants.RECEIPT_EXTERNAL_CATEGORY_TASK_NAME,
    autoretry_for=(ExternalCategoryResponseError, httpx.HTTPError),
    max_retries=2,
    retry_backoff=True,
    acks_late=True,
)
def categorize_receipt_product(product_id: int) -> None:
    """Run an isolated optional external fallback for one product."""
    product = _get_product_repository().get_external_category_candidate(
        product_id,
    )
    if product is None:
        logger.info(
            'receipt_external_category_skipped',
            product_id=product_id,
            reason='not_eligible',
        )
        return
    service = _get_external_product_category_service()
    if not service.enabled:
        logger.info(
            'receipt_external_category_skipped',
            product_id=product_id,
            reason='disabled',
        )
        return
    try:
        service.categorize_product(product)
    except (ExternalCategoryResponseError, httpx.HTTPError) as error:
        reason = (
            'invalid_response'
            if isinstance(error, ExternalCategoryResponseError)
            else 'model_unavailable'
        )
        logger.warning(
            'receipt_external_category_failed',
            product_id=product_id,
            reason=reason,
            error=str(error),
        )
        raise


@shared_task(name=constants.RECEIPT_CATEGORY_TWIN_TASK_NAME)  # type: ignore[untyped-decorator]
def find_category_merge_proposals() -> dict[str, int]:
    """Find twin-category pairs across users and save pending proposals."""
    detection = _get_category_twin_detection_service()
    if not detection.enabled:
        logger.info(
            'receipt_category_twin_detection_skipped',
            reason='disabled',
        )
        return {'users': 0, 'proposals': 0}

    proposal_service = _get_category_merge_proposal_service()
    user_ids = ProductCategory.objects.values_list('user', flat=True).distinct()
    users = User.objects.filter(pk__in=user_ids)

    processed = 0
    proposals = 0
    for user in users.iterator():
        try:
            pairs = detection.find_duplicate_pairs(user)
        except (CategoryTwinDetectionError, httpx.HTTPError) as error:
            logger.warning(
                'receipt_category_twin_detection_failed',
                user_id=user.pk,
                error=str(error),
            )
            continue
        processed += 1
        for category_a, category_b in pairs:
            if proposal_service.create_if_absent(
                user=user,
                category_a=category_a,
                category_b=category_b,
            ):
                proposals += 1

    logger.info(
        'receipt_category_twin_detection_done',
        users=processed,
        proposals=proposals,
    )
    return {'users': processed, 'proposals': proposals}


@shared_task(name='receipts.cleanup_stale_receipt_processing_logs')  # type: ignore[untyped-decorator]
def cleanup_stale_receipt_processing_logs() -> dict[str, int]:
    """Recover stalled receipt-processing journal entries for retry."""
    service = _get_receipt_processing_service()
    now = timezone.now()
    hard_limit_seconds = int(
        getattr(settings, 'CELERY_TASK_TIME_LIMIT', 30 * 60),
    )
    stuck_threshold = now - timedelta(
        seconds=hard_limit_seconds + _PROCESSING_GRACE_MINUTES * 60,
    )

    recovered = 0
    stuck = ReceiptProcessingLog.objects.filter(
        status=ReceiptProcessingStatus.PROCESSING,
        processing_started_at__lt=stuck_threshold,
    )
    for log in stuck:
        service.mark_failed(
            log=log,
            error_message=str(_TIMEOUT_RECOVERY_MESSAGE),
            task_id=log.task_id,
        )
        recovered += 1
    logger.info(
        'receipt_processing_log_cleanup',
        recovered=recovered,
    )
    return {'recovered': recovered}
