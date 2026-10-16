"""Celery tasks for user-related async operations."""

from typing import Any

import structlog
from celery import shared_task
from django.db import InterfaceError, OperationalError
from django.utils.translation import gettext_lazy as _

from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
)
from hasta_la_vista_money.users.services.bank_statement import (
    BankStatementParseError,
)
from hasta_la_vista_money.users.services.bank_statement_reconciliation import (
    BankStatementReconciliationService,
)

logger = structlog.get_logger(__name__)

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

    try:
        upload = BankStatementUpload.objects.select_related(
            'user',
            'account',
        ).get(id=upload_id)
        if upload.account.is_archived or upload.account.is_deposit:
            raise BankStatementParseError(
                _('Архивный счёт или счёт вклада недоступен для импорта.'),
            )
        _initialize_upload(upload, self)

        service = ApplicationContainer().users.bank_statement_import_service()
        result = service.import_statement(upload)

        upload.account.refresh_from_db(fields=['balance'])
        if result.closing_balance is not None:
            upload.statement_closing_balance = result.closing_balance
            upload.account_balance_after = upload.account.balance
            upload.balance_discrepancy = (
                result.closing_balance - upload.account.balance
            )

        if BankStatementRow.objects.filter(
            upload=upload,
            decision=BankStatementRow.Decision.PENDING,
        ).exists():
            upload.status = BankStatementUpload.Status.AWAITING_CONFIRMATION
        else:
            upload.status = BankStatementUpload.Status.COMPLETED
        upload.progress = 100
        upload.save(
            update_fields=[
                'status',
                'progress',
                'updated_at',
                'statement_closing_balance',
                'account_balance_after',
                'balance_discrepancy',
            ],
        )
        BankStatementReconciliationService.refresh_outcome_counts(upload)

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

    except BankStatementParseError as e:
        logger.exception(
            'bank_statement_parse_failed',
            upload_id=upload_id,
        )
        _mark_upload_failed(upload_id, f'{_("Ошибка парсинга")}: {e!s}')
        raise

    except RETRYABLE_ERRORS as e:
        logger.exception(
            'bank_statement_task_transient_error',
            upload_id=upload_id,
        )
        if self.request.retries >= self.max_retries:
            _mark_upload_failed(
                upload_id,
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
        _mark_upload_failed(upload_id, f'{_("Непредвиденная ошибка")}: {e!s}')
        raise


def _mark_upload_failed(upload_id: int, message: str) -> None:
    """Перевести загрузку в FAILED с текстом ошибки."""
    try:
        upload = BankStatementUpload.objects.get(id=upload_id)
    except BankStatementUpload.DoesNotExist:
        return
    upload.status = BankStatementUpload.Status.FAILED
    upload.failed_count = 1
    upload.error_message = message
    upload.save(
        update_fields=[
            'status',
            'failed_count',
            'error_message',
            'updated_at',
        ],
    )


def _initialize_upload(
    upload: BankStatementUpload,
    task: shared_task,
) -> None:
    """Перевести запись загрузки в статус «обрабатывается».

    Args:
        upload: Экземпляр ``BankStatementUpload`` для инициализации.
        task: Экземпляр Celery-задачи для получения ``request.id``.
    """
    upload.status = BankStatementUpload.Status.PROCESSING
    upload.celery_task_id = task.request.id
    upload.failed_count = 0
    upload.error_message = ''
    upload.save(
        update_fields=[
            'status',
            'celery_task_id',
            'failed_count',
            'error_message',
            'updated_at',
        ],
    )
