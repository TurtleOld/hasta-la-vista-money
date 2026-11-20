"""Celery tasks for user-related async operations."""

from typing import TYPE_CHECKING, Any, Protocol, cast

import structlog
from celery import shared_task
from django.db import InterfaceError, OperationalError
from django.utils.translation import gettext_lazy as _

from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.users.models import BankStatementUpload
from hasta_la_vista_money.users.protocols.services import (
    BankStatementImportServiceProtocol,
)
from hasta_la_vista_money.users.services.bank_statement import (
    BankStatementParseError,
)
from hasta_la_vista_money.users.services.bank_statement_import import (
    GENERATION_BUSY,
    GENERATION_CURRENT,
    GENERATION_STARTED,
    StatementGeneration,
    StatementGenerationExpiredError,
    StatementImportResult,
)

logger = structlog.get_logger(__name__)


if TYPE_CHECKING:

    class TaskProtocol(Protocol):
        """Static surface of a bound Celery task used by callers."""

        def apply(
            self,
            args: list[Any] | None = ...,
            kwargs: dict[str, Any] | None = ...,
            **options: Any,
        ) -> Any: ...

        def delay(self, *args: Any, **kwargs: Any) -> Any: ...


RETRYABLE_ERRORS = (OperationalError, InterfaceError)


def _cleanup_expired_bank_statements() -> dict[str, int]:
    """Remove expired statement data and return the number cleaned."""
    service = ApplicationContainer().users.bank_statement_retention_service()
    return {'cleaned': service.cleanup_expired()}


cleanup_expired_bank_statements = shared_task(
    name='users.cleanup_expired_bank_statements',
)(_cleanup_expired_bank_statements)


@shared_task(  # type: ignore[untyped-decorator]
    bind=True,
    max_retries=constants.STATEMENT_IMPORT_MAX_RETRIES,
    acks_late=True,
    reject_on_worker_lost=True,
)
def process_bank_statement_task(
    self: Any,
    upload_id: int,
) -> dict[str, int]:
    """Обработать PDF-выписку в фоне: импортировать транзакции и сверить баланс.

    Тонкий адаптер над ``BankStatementImportService``: сервис не имеет
    доступа к ``request.container`` (его нет у Celery-задачи), поэтому
    достаётся из ``ApplicationContainer()`` напрямую. Сама логика разбора
    PDF, дедупликации, категоризации и проводки движения инкапсулирована
    в сервисе; здесь остаётся только жизненный цикл записи загрузки.

    Args:
        self: Экземпляр Celery-задачи (bind=True).
        upload_id: Первичный ключ ``BankStatementUpload`` для обработки.

    Returns:
        Словарь с ключами ``income_count``, ``expense_count``,
        ``skipped_count``, ``needs_transfer_count``, ``total_count``.

    Raises:
        BankStatementParseError: Если PDF не удалось разобрать.
    """
    logger.info(
        'bank_statement_task_started',
        upload_id=upload_id,
    )
    service: BankStatementImportServiceProtocol | None = None
    generation: StatementGeneration | None = None

    try:
        upload = BankStatementUpload.objects.select_related(
            'user',
            'account',
        ).get(id=upload_id)
        service = cast(
            'BankStatementImportServiceProtocol',
            ApplicationContainer().users.bank_statement_import_service(),
        )
        generation = service.capture_generation(upload)
        captured_generation = generation
        _assert_account_importable(upload)
        state = _start_generation(
            service,
            upload,
            captured_generation,
            self.request.id or '',
        )
        if state == GENERATION_BUSY:
            logger.warning(
                'bank_statement_task_busy',
                upload_id=upload_id,
            )
            return {
                'income_count': upload.income_count,
                'expense_count': upload.expense_count,
                'skipped_count': upload.skipped_count,
                'needs_transfer_count': upload.needs_transfer_count,
                'total_count': 0,
            }

        upload.refresh_from_db()
        result = service.import_statement(upload, generation=generation)
        _finalize_generation(
            service,
            upload,
            captured_generation,
            result,
            self.request.id or '',
        )

        upload.refresh_from_db()
        logger.info(
            'bank_statement_task_completed',
            upload_id=upload_id,
            income=result.income_count,
            expenses=result.expense_count,
            skipped=result.skipped_count,
            discrepancy=str(upload.balance_discrepancy),
        )

        return {
            'income_count': result.income_count,
            'expense_count': result.expense_count,
            'skipped_count': result.skipped_count,
            'needs_transfer_count': result.needs_transfer_count,
            'total_count': result.income_count + result.expense_count,
        }

    except BankStatementUpload.DoesNotExist:
        logger.exception(
            'bank_statement_upload_not_found',
            upload_id=upload_id,
        )
        raise

    except StatementGenerationExpiredError:
        # An old parse must not post against or rewrite another generation.
        if service is not None and generation is not None:
            outcome = service.resolve_expired_generation(
                upload_id,
                generation,
                self.request.id or '',
            )
            logger.warning(
                'bank_statement_generation_expired',
                upload_id=upload_id,
                outcome=outcome,
            )
        raise

    except BankStatementParseError as e:
        logger.exception(
            'bank_statement_parse_failed',
            upload_id=upload_id,
        )
        _mark_failure_if_current(
            service,
            generation,
            upload_id,
            self.request.id or '',
            f'{_("Ошибка парсинга")}: {e!s}',
        )
        raise

    except RETRYABLE_ERRORS as e:
        logger.exception(
            'bank_statement_task_transient_error',
            upload_id=upload_id,
        )
        if self.request.retries >= self.max_retries:
            _mark_failure_if_current(
                service,
                generation,
                upload_id,
                self.request.id or '',
                f'{_("Непредвиденная ошибка")}: {e!s}',
            )
        raise self.retry(
            exc=e,
            countdown=constants.STATEMENT_IMPORT_RETRY_DELAY_SECONDS,
        ) from e

    except Exception as e:
        logger.exception(
            'bank_statement_task_unexpected_error',
            upload_id=upload_id,
        )
        _mark_failure_if_current(
            service,
            generation,
            upload_id,
            self.request.id or '',
            f'{_("Непредвиденная ошибка")}: {e!s}',
        )
        raise


process_bank_statement_typed = cast(
    'TaskProtocol',
    process_bank_statement_task,
)


def _assert_account_importable(upload: BankStatementUpload) -> None:
    """Reject imports into archived or deposit accounts."""
    if upload.account.is_archived or upload.account.is_deposit:
        raise BankStatementParseError(
            _('Архивный счёт или счёт вклада недоступен для импорта.'),
        )


def _start_generation(
    service: BankStatementImportServiceProtocol,
    upload: BankStatementUpload,
    generation: StatementGeneration,
    task_id: str,
) -> str:
    """Start a job only for the upload generation it captured."""
    state: str = service.start_upload(upload.pk, generation, task_id)
    if state not in (GENERATION_BUSY, GENERATION_STARTED):
        service.resolve_expired_generation(upload.pk, generation, task_id)
        raise StatementGenerationExpiredError(state)
    return state


def _finalize_generation(
    service: BankStatementImportServiceProtocol,
    upload: BankStatementUpload,
    generation: StatementGeneration,
    result: StatementImportResult,
    task_id: str,
) -> None:
    """Finalize only while the parsed generation is still current."""
    state = service.finalize_import(
        upload,
        generation,
        closing_balance=result.closing_balance,
    )
    if state != GENERATION_CURRENT:
        service.resolve_expired_generation(upload.pk, generation, task_id)
        raise StatementGenerationExpiredError(state)


def _mark_failure_if_current(
    service: BankStatementImportServiceProtocol | None,
    generation: StatementGeneration | None,
    upload_id: int,
    task_id: str,
    message: str,
) -> None:
    """Record a failure only while this run owns the upload generation."""
    if service is None or generation is None:
        return
    service.mark_failure_if_current(
        upload_id,
        generation,
        task_id,
        message,
    )
