"""Celery tasks for user-related async operations."""

import logging
from typing import Any

from celery import shared_task
from django.utils.translation import gettext_lazy as _

from config.containers import ApplicationContainer
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

logger = logging.getLogger(__name__)


def _cleanup_expired_bank_statements() -> dict[str, int]:
    """Remove expired statement data and return the number cleaned."""
    service = ApplicationContainer().users.bank_statement_retention_service()
    return {'cleaned': service.cleanup_expired()}


cleanup_expired_bank_statements = shared_task(
    name='users.cleanup_expired_bank_statements',
)(_cleanup_expired_bank_statements)


@shared_task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
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
        ``skipped_count``, ``total_count``.

    Raises:
        BankStatementParseError: Если PDF не удалось разобрать.
    """
    logger.info(
        'Starting bank statement processing task for upload_id=%d',
        upload_id,
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
                'statement_closing_balance',
                'account_balance_after',
                'balance_discrepancy',
            ],
        )
        BankStatementReconciliationService.refresh_outcome_counts(upload)

        logger.info(
            'Completed: %d income, %d expenses, %d skipped, discrepancy=%s',
            result.income_count,
            result.expense_count,
            result.skipped_count,
            upload.balance_discrepancy,
        )

        return {
            'income_count': result.income_count,
            'expense_count': result.expense_count,
            'skipped_count': result.skipped_count,
            'total_count': result.income_count + result.expense_count,
        }

    except BankStatementUpload.DoesNotExist:
        logger.exception('Upload with id=%d not found', upload_id)
        raise

    except BankStatementParseError as e:
        logger.exception('Failed to parse bank statement')
        try:
            upload = BankStatementUpload.objects.get(id=upload_id)
            upload.status = BankStatementUpload.Status.FAILED
            upload.failed_count = 1
            upload.error_message = f'Ошибка парсинга: {e!s}'
            upload.save(
                update_fields=['status', 'failed_count', 'error_message'],
            )
        except BankStatementUpload.DoesNotExist:
            pass
        raise

    except Exception as e:
        logger.exception('Unexpected error processing bank statement')
        try:
            upload = BankStatementUpload.objects.get(id=upload_id)
            upload.status = BankStatementUpload.Status.FAILED
            upload.failed_count = 1
            upload.error_message = f'Непредвиденная ошибка: {e!s}'
            upload.save(
                update_fields=['status', 'failed_count', 'error_message'],
            )
        except BankStatementUpload.DoesNotExist:
            pass
        raise self.retry(exc=e, countdown=60) from e


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
    upload.progress = 0
    upload.failed_count = 0
    upload.save(
        update_fields=[
            'status',
            'celery_task_id',
            'progress',
            'failed_count',
        ],
    )
