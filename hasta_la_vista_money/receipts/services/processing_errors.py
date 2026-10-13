"""Receipt processing errors classified by the pipeline stage they stop at.

The pipeline wraps each step in :func:`processing_stage`; any exception
raised inside becomes a single :class:`ReceiptProcessingError` carrying the
error code, the stage, a user-facing message and log-safe details.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Final

from celery.exceptions import SoftTimeLimitExceeded
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money.receipts.models import (
    ReceiptProcessingErrorCode,
    ReceiptProcessingStage,
)
from hasta_la_vista_money.receipts.services.fns_client import (
    FNSAuthenticationError,
    FNSConfigurationError,
    FNSMalformedResponseError,
    FNSRateLimitError,
    FNSTemporaryUnavailableError,
    FNSTimeoutError,
    FNSUnauthorizedError,
)
from hasta_la_vista_money.receipts.services.fns_mapper import (
    FNSReceiptMappingError,
)
from hasta_la_vista_money.receipts.services.fns_qr import (
    QRCodeError,
    QRCodeNotFoundError,
)
from hasta_la_vista_money.receipts.services.receipt_creator import (
    ReceiptLineError,
    ReceiptTotalError,
)
from hasta_la_vista_money.receipts.validators.parsed_receipt import (
    ReceiptParseValidationError,
)

Code = ReceiptProcessingErrorCode

RETRYABLE_ERROR_CODES: Final = frozenset(
    {Code.FNS_UNAVAILABLE, Code.FNS_RATE_LIMITED},
)
REPORTABLE_ERROR_CODES: Final = frozenset(
    {
        Code.LINE_INVALID,
        Code.TOTAL_INVALID,
        Code.RECEIPT_INVALID,
        Code.FNS_BAD_RESPONSE,
        Code.UNEXPECTED,
    },
)

_AMOUNTS_REJECTED_MESSAGE = _(
    'Чек получен из ФНС, но не прошёл проверку сумм. '
    'Удалите запись и внесите чек вручную или повторите '
    'после обновления приложения.',
)
TIMEOUT_RECOVERY_MESSAGE: Final = _(
    'Обработка прервана по таймауту. Попробуйте ещё раз.',
)

USER_MESSAGES: Final = {
    Code.IMAGE_MISSING: _(
        'Файл изображения чека не найден. Загрузите чек заново.',
    ),
    Code.QR_NOT_FOUND: _(
        'Не удалось найти QR-код на изображении чека. '
        'Загрузите более чёткое фото, где QR-код виден полностью.',
    ),
    Code.QR_INVALID: _(
        'QR-код на изображении не похож на QR-код кассового чека ФНС. '
        'Проверьте фото и загрузите чек заново.',
    ),
    Code.FNS_UNAVAILABLE: _(
        'Сервис ФНС временно недоступен. Попробуйте обработать чек позже.',
    ),
    Code.FNS_RATE_LIMITED: _(
        'Сервис ФНС временно ограничил частоту запросов. '
        'Попробуйте обработать чек через несколько минут.',
    ),
    Code.FNS_AUTH_FAILED: _(
        'Не удалось авторизоваться в ФНС. Проверьте настройки интеграции.',
    ),
    Code.FNS_BAD_RESPONSE: _(
        'ФНС вернула данные чека в неожиданном формате. '
        'Удалите запись и внесите чек вручную или повторите '
        'после обновления приложения.',
    ),
    Code.RECEIPT_INVALID: _(
        'Данные чека из ФНС не прошли проверку. '
        'Удалите запись и внесите чек вручную.',
    ),
    Code.LINE_INVALID: _AMOUNTS_REJECTED_MESSAGE,
    Code.TOTAL_INVALID: _AMOUNTS_REJECTED_MESSAGE,
    Code.TIMED_OUT: _(
        'Обработка заняла слишком много времени и была прервана. '
        'Попробуйте ещё раз.',
    ),
    Code.UNEXPECTED: _(
        'Произошла непредвиденная ошибка при обработке чека. '
        'Попробуйте ещё раз.',
    ),
}

_CODES_BY_EXCEPTION: Final[tuple[tuple[Any, Code], ...]] = (
    ((SoftTimeLimitExceeded, TimeoutError), Code.TIMED_OUT),
    (QRCodeNotFoundError, Code.QR_NOT_FOUND),
    (QRCodeError, Code.QR_INVALID),
    (FNSRateLimitError, Code.FNS_RATE_LIMITED),
    (
        (FNSAuthenticationError, FNSConfigurationError, FNSUnauthorizedError),
        Code.FNS_AUTH_FAILED,
    ),
    (
        (FNSTemporaryUnavailableError, FNSTimeoutError),
        Code.FNS_UNAVAILABLE,
    ),
    (
        (FNSMalformedResponseError, FNSReceiptMappingError),
        Code.FNS_BAD_RESPONSE,
    ),
    (ReceiptParseValidationError, Code.RECEIPT_INVALID),
    (ReceiptLineError, Code.LINE_INVALID),
    (ReceiptTotalError, Code.TOTAL_INVALID),
)

_MALFORMED_DATA_ERRORS: Final = (
    json.JSONDecodeError,
    KeyError,
    TypeError,
    ValueError,
)


class ReceiptImageMissingError(Exception):
    """Raised when a journal entry has neither an image nor a QR string."""


class ReceiptProcessingError(Exception):
    """A receipt processing error with its cause and pipeline stage."""

    def __init__(
        self,
        *,
        code: ReceiptProcessingErrorCode,
        stage: ReceiptProcessingStage | None,
        user_message: str,
        cause: BaseException,
        retry_after: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f'{stage or "-"}:{code}')
        self.code = code
        self.stage = stage
        self.user_message = user_message
        self.cause = cause
        self.retry_after = retry_after
        self.detail = detail or {}

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE_ERROR_CODES


def classify_processing_error(
    exc: BaseException,
    stage: ReceiptProcessingStage | None,
) -> ReceiptProcessingError:
    """Turn an exception raised at ``stage`` into a processing error."""
    if isinstance(exc, ReceiptProcessingError):
        return exc
    code = _code_for(exc, stage)
    user_message = str(USER_MESSAGES[code])
    if isinstance(exc, ReceiptParseValidationError) and exc.user_message:
        user_message = exc.user_message
    return ReceiptProcessingError(
        code=code,
        stage=stage,
        user_message=user_message,
        cause=exc,
        retry_after=(
            exc.retry_after if isinstance(exc, FNSRateLimitError) else None
        ),
        detail=_detail_for(exc),
    )


@contextmanager
def processing_stage(stage: ReceiptProcessingStage) -> Iterator[None]:
    """Classify any exception raised inside the block as failing at stage."""
    try:
        yield
    except ReceiptProcessingError:
        raise
    except Exception as exc:
        raise classify_processing_error(exc, stage) from exc


def _code_for(
    exc: BaseException,
    stage: ReceiptProcessingStage | None,
) -> ReceiptProcessingErrorCode:
    if isinstance(exc, ReceiptImageMissingError):
        return Code.IMAGE_MISSING
    for exception_types, code in _CODES_BY_EXCEPTION:
        if isinstance(exc, exception_types):
            return code
    if stage == ReceiptProcessingStage.QR and isinstance(exc, ValueError):
        return Code.QR_INVALID
    if stage == ReceiptProcessingStage.MAP and isinstance(
        exc,
        _MALFORMED_DATA_ERRORS,
    ):
        return Code.FNS_BAD_RESPONSE
    return Code.UNEXPECTED


def _detail_for(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, ReceiptLineError):
        return {
            'line_index': exc.index,
            'line_error': str(exc.error),
            'line_price': str(exc.price),
            'line_quantity': str(exc.quantity),
            'line_amount': str(exc.amount),
        }
    if isinstance(exc, ReceiptTotalError):
        return {'total_sum': str(exc.total_sum)}
    if isinstance(exc, QRCodeError):
        return {'image_width': exc.width, 'image_height': exc.height}
    return {}
