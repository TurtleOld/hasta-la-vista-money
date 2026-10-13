"""Celery tasks for background receipt processing.

The view layer enqueues processing-log jobs after persisting their source
data. All inference, parsing and state transitions live here so the work
survives the user closing the page.
"""

import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any, cast

import httpx
import structlog
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from config.containers import ApplicationContainer
from core.repositories.protocols import ProductRepositoryProtocol
from hasta_la_vista_money import constants
from hasta_la_vista_money.receipts.models import (
    ProductCategory,
    ReceiptProcessingErrorCode,
    ReceiptProcessingLog,
    ReceiptProcessingStage,
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
from hasta_la_vista_money.receipts.services.category_classifier import (
    ReceiptItemCategoryService,
)
from hasta_la_vista_money.receipts.services.category_twin_detection import (
    CategoryTwinDetectionError,
)
from hasta_la_vista_money.receipts.services.external_category import (
    ExternalCategoryResponseError,
)
from hasta_la_vista_money.receipts.services.fns_client import FNSClient
from hasta_la_vista_money.receipts.services.fns_mapper import (
    map_fns_receipt_to_receipt_data,
)
from hasta_la_vista_money.receipts.services.fns_qr import (
    QRCodeExtractor,
    parse_fns_qr,
)
from hasta_la_vista_money.receipts.services.processing_errors import (
    TIMEOUT_RECOVERY_MESSAGE,
    ReceiptImageMissingError,
    ReceiptProcessingError,
    classify_processing_error,
    processing_stage,
)
from hasta_la_vista_money.receipts.services.receipt_processing_service import (
    ReceiptProcessingService,
)
from hasta_la_vista_money.receipts.validators.parsed_receipt import (
    validate_receipt_parse_payload,
)
from hasta_la_vista_money.users.models import User

logger = structlog.get_logger(__name__)

_PROCESSING_GRACE_MINUTES = 10


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
    with processing_stage(ReceiptProcessingStage.FNS):
        fns_payload = FNSClient().fetch_receipt(raw_qr)
    with processing_stage(ReceiptProcessingStage.MAP):
        receipt_data = map_fns_receipt_to_receipt_data(fns_payload)
    _categorize_items(log, receipt_data)
    _fill_retail_place(log, receipt_data)
    with processing_stage(ReceiptProcessingStage.VALIDATE):
        validated = validate_receipt_parse_payload(receipt_data).to_dict()
    validated['_fns_raw'] = fns_payload
    return validated


@contextmanager
def _best_effort(event: str, log: ReceiptProcessingLog) -> Iterator[None]:
    try:
        yield
    except Exception:
        logger.warning(
            event,
            processing_log_id=log.pk,
            user_id=log.user.pk,
            exc_info=True,
        )


def _categorize_items(
    log: ReceiptProcessingLog,
    receipt_data: dict[str, Any],
) -> None:
    with _best_effort('receipt_processing_categorization_failed', log):
        receipt_data['items'] = (
            _get_receipt_item_category_service().categorize_items(
                user=log.user,
                items=receipt_data.get('items', []),
            )
        )


def _fill_retail_place(
    log: ReceiptProcessingLog,
    receipt_data: dict[str, Any],
) -> None:
    inn = receipt_data.get('inn')
    if not inn or receipt_data.get('retail_place'):
        return
    with _best_effort('receipt_processing_seller_lookup_failed', log):
        seller = SellerRepository().find_by_inn(user=log.user, inn=inn)
        if seller and seller.retail_place not in (None, '', 'Нет данных'):
            receipt_data['retail_place'] = seller.retail_place


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
    with processing_stage(ReceiptProcessingStage.QR):
        raw_qr = log.qr_raw
        if not raw_qr:
            if not log.image_file:
                raise ReceiptImageMissingError
            with log.image_file.open('rb') as image_fp:
                qr_data = QRCodeExtractor().extract(image_fp)
            raw_qr = qr_data.raw
            fiscal_key = qr_data.fiscal_key
        else:
            fiscal_key = log.fiscal_key or parse_fns_qr(raw_qr).fiscal_key
    with processing_stage(ReceiptProcessingStage.CLAIM):
        claimed = service.claim_fiscal_key(
            log=log,
            fiscal_key=fiscal_key,
            task_id=task_id,
        )
    if not claimed:
        return None
    return _run_fns_pipeline_from_raw(log, raw_qr)


def _retry_countdown(error: ReceiptProcessingError, retries: int) -> int:
    if error.retry_after is not None:
        return min(
            error.retry_after,
            constants.RECEIPT_PROCESSING_RETRY_MAX_COUNTDOWN_SECONDS,
        )
    jitter = secrets.randbelow(
        constants.RECEIPT_PROCESSING_RETRY_JITTER_SECONDS + 1,
    )
    backoff = constants.RECEIPT_PROCESSING_RETRY_BASE_SECONDS * 2**retries
    return int(backoff) + jitter


def _log_context(
    log: ReceiptProcessingLog,
    task_id: str,
    error: ReceiptProcessingError,
) -> dict[str, Any]:
    return {
        'processing_log_id': log.pk,
        'user_id': log.user.pk,
        'account_id': log.account.pk,
        'task_id': task_id,
        'fiscal_key': log.fiscal_key,
        'error_code': str(error.code),
        'error_stage': str(error.stage or ''),
        'exc_type': type(error.cause).__name__,
        **error.detail,
    }


@shared_task(  # type: ignore[untyped-decorator]
    bind=True,
    name='receipts.process_receipt_processing_log',
    max_retries=constants.RECEIPT_PROCESSING_MAX_RETRIES,
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
        logger.info(
            'receipt_processing_outcome_discarded',
            processing_log_id=log.pk,
            task_id=self.request.id,
            status=log.status,
        )
        return

    service = _get_receipt_processing_service()
    task_id = str(self.request.id)
    try:
        receipt_data = _run_processing_log_pipeline(log, service, task_id)
        if receipt_data is None:
            return
        with processing_stage(ReceiptProcessingStage.CREATE):
            service.complete(
                log=log,
                receipt_data=receipt_data,
                task_id=task_id,
            )
    except Exception as exc:
        error = classify_processing_error(exc, stage=None)
    else:
        return

    context = _log_context(log, task_id, error)
    if error.retryable and self.request.retries < self.max_retries:
        if service.record_retry(
            log=log,
            error_code=error.code,
            error_stage=error.stage,
            task_id=task_id,
        ):
            countdown = _retry_countdown(error, self.request.retries)
            logger.warning(
                'receipt_processing_retry_scheduled',
                retries=self.request.retries,
                countdown=countdown,
                **context,
            )
            raise self.retry(exc=error.cause, countdown=countdown)
    elif service.mark_failed(
        log=log,
        error_code=error.code,
        error_stage=error.stage,
        error_message=error.user_message,
        task_id=task_id,
    ):
        logger.warning(
            'receipt_processing_failed',
            exc_info=error.cause,
            **context,
        )
        return
    logger.info('receipt_processing_outcome_discarded', **context)


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
        if service.mark_failed(
            log=log,
            error_code=ReceiptProcessingErrorCode.TIMED_OUT,
            error_stage=None,
            error_message=str(TIMEOUT_RECOVERY_MESSAGE),
            task_id=log.task_id,
        ):
            recovered += 1
    logger.info(
        'receipt_processing_log_cleanup',
        recovered=recovered,
    )
    return {'recovered': recovered}
