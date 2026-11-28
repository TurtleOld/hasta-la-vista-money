"""Celery tasks for user-related async operations."""

from typing import Any

import structlog
from celery import shared_task
from django.db import InterfaceError, OperationalError, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.users.models import BankStatementUpload
from hasta_la_vista_money.users.services.bank_statement import (
    BankStatementParseError,
)
from hasta_la_vista_money.users.services.bank_statement_import import (
    StatementImportResult,
)
from hasta_la_vista_money.users.services.bank_statement_reconciliation import (
    BankStatementReconciliationService,
)
from hasta_la_vista_money.users.services.statement_completion import (
    has_open_rows,
    is_statement_complete,
)

logger = structlog.get_logger(__name__)

RETRYABLE_ERRORS = (OperationalError, InterfaceError)


def _cleanup_expired_bank_statements() -> dict[str, int]:
    """Remove expired statement data and return the number cleaned."""
    service = ApplicationContainer().users.bank_statement_retention_service()
    return {'cleaned': service.cleanup_expired()}


def _store_statement_balance(
    upload: BankStatementUpload,
    result: StatementImportResult,
) -> None:
    """Store only balance metadata the parser actually confirmed.

    A date without confirmed closing semantics stays a bank date; no exact
    moment or currency is inferred from the account.
    """
    upload.statement_closing_balance = result.closing_balance
    upload.balance_currency = result.closing_balance_currency or ''
    upload.balance_moment = result.closing_balance_moment
    upload.balance_bank_date = result.closing_balance_date
    semantics = result.closing_balance_semantics
    if semantics == BankStatementUpload.BalanceType.EXACT_MOMENT:
        upload.balance_type = BankStatementUpload.BalanceType.EXACT_MOMENT
    elif semantics == BankStatementUpload.BalanceType.CLOSING_DAY:
        upload.balance_type = BankStatementUpload.BalanceType.CLOSING_DAY
    else:
        upload.balance_type = BankStatementUpload.BalanceType.UNKNOWN


def _statement_result_counts(
    result: StatementImportResult,
) -> dict[str, int]:
    """Return the public task counters for one import result."""
    return {
        'income_count': result.income_count,
        'expense_count': result.expense_count,
        'skipped_count': result.skipped_count,
        'needs_transfer_count': result.needs_transfer_count,
        'total_count': result.income_count + result.expense_count,
    }


def _empty_result_counts() -> dict[str, int]:
    """Return counters without exposing bank data of a stopped run."""
    return {
        'income_count': 0,
        'expense_count': 0,
        'skipped_count': 0,
        'needs_transfer_count': 0,
        'total_count': 0,
    }


def _lock_active_run(
    upload_id: int,
    run_id: str | None,
) -> BankStatementUpload | None:
    """Lock the upload and keep it only while this worker owns the run.

    Cleanup takes the same lock, clears the run id and marks the bank data
    cleaned. A worker that resumes afterwards must not write the balance
    or status back, so the caller finalizes only a non-null result.
    """
    upload = (
        BankStatementUpload.objects.select_for_update()
        .select_related('account', 'user')
        .get(pk=upload_id)
    )
    if (
        upload.retention_cleaned_at is not None
        or upload.expires_at <= timezone.now()
        or upload.celery_task_id != str(run_id or '')
    ):
        return None
    return upload


def _finalize_upload(
    upload_id: int,
    run_id: str | None,
    result: StatementImportResult,
    container: ApplicationContainer,
) -> BankStatementUpload | None:
    """Store the run outcome only while this worker still owns the upload."""
    with transaction.atomic():
        upload = _lock_active_run(upload_id, run_id)
        if upload is None:
            return None
        upload.account.refresh_from_db(fields=['balance'])
        BankStatementReconciliationService.refresh_outcome_counts(upload)
        empty_parse = upload.total_transactions == 0
        complete = is_statement_complete(upload)
        unresolved = has_open_rows(upload)
        _store_statement_balance(upload, result)

        if empty_parse:
            upload.error_message = str(
                _(
                    'В выписке не удалось выделить ни одной операции; '
                    'полнота не подтверждена.',
                ),
            )
        if empty_parse or not complete:
            upload.status = BankStatementUpload.Status.AWAITING_CONFIRMATION
        else:
            upload.status = BankStatementUpload.Status.COMPLETED
        upload.progress = 100
        upload.save(
            update_fields=[
                'status',
                'progress',
                'updated_at',
                'error_message',
                'statement_closing_balance',
                'balance_currency',
                'balance_moment',
                'balance_bank_date',
                'balance_type',
            ],
        )
        if result.closing_balance is not None and not unresolved:
            balance_service = (
                container.users.statement_balance_verification_service()
            )
            upload = balance_service.verify(upload)
    return upload


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
    run_id: str | None = None,
) -> dict[str, int]:
    """Обработать PDF-выписку в фоне: импортировать транзакции и сверить баланс.

    Тонкий адаптер над ``BankStatementImportService``: сервис не имеет
    доступа к ``request.container`` (его нет у Celery-задачи), поэтому
    достаётся из ``ApplicationContainer()`` напрямую. Сама логика разбора
    PDF, дедупликации, категоризации и проводки движения инкапсулирована
    в сервисе; здесь остаётся только жизненный цикл записи загрузки.

    The run identifier is assigned before the task is published. A stale
    delivery with another identifier cannot claim the upload, so it never
    writes PROCESSING or FAILED and never returns bank data.

    Args:
        self: Экземпляр Celery-задачи (bind=True).
        upload_id: Первичный ключ ``BankStatementUpload`` для обработки.
        run_id: Идентификатор запуска, назначенный до публикации задачи.
            Без него используется идентификатор текущей доставки Celery.

    Returns:
        Словарь с ключами ``income_count``, ``expense_count``,
        ``skipped_count``, ``needs_transfer_count``, ``total_count``.

    Raises:
        BankStatementParseError: Если PDF не удалось разобрать.
    """
    run_id = run_id or self.request.id
    logger.info(
        'bank_statement_task_started',
        upload_id=upload_id,
        run_id=run_id,
    )

    try:
        upload = _claim_run(upload_id, run_id)
        if upload is None:
            logger.info(
                'bank_statement_run_not_owned',
                upload_id=upload_id,
                run_id=run_id,
            )
            return _empty_result_counts()
        if upload.account.is_archived or upload.account.is_deposit:
            raise BankStatementParseError(
                _('Архивный счёт или счёт вклада недоступен для импорта.'),
            )

        container = ApplicationContainer()
        service = container.users.bank_statement_import_service()
        result = service.import_statement(upload)
        if result.stopped:
            logger.info(
                'bank_statement_run_stopped_after_retention',
                upload_id=upload_id,
            )
            return _empty_result_counts()

        finalized = _finalize_upload(
            upload_id,
            run_id,
            result,
            container,
        )
        if finalized is None:
            logger.info(
                'bank_statement_finalization_skipped',
                upload_id=upload_id,
            )
            return _empty_result_counts()
        upload = finalized

        logger.info(
            'bank_statement_task_completed',
            upload_id=upload_id,
            income=result.income_count,
            expenses=result.expense_count,
            skipped=result.skipped_count,
            discrepancy=str(upload.balance_discrepancy),
        )

        return _statement_result_counts(result)

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
        _mark_upload_failed(
            upload_id,
            run_id,
            f'{_("Ошибка парсинга")}: {e!s}',
        )
        raise

    except RETRYABLE_ERRORS as e:
        logger.exception(
            'bank_statement_task_transient_error',
            upload_id=upload_id,
        )
        if self.request.retries >= self.max_retries:
            _mark_upload_failed(
                upload_id,
                run_id,
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
        _mark_upload_failed(
            upload_id,
            run_id,
            f'{_("Непредвиденная ошибка")}: {e!s}',
        )
        raise


def _mark_upload_failed(
    upload_id: int,
    run_id: str,
    message: str,
) -> None:
    """Перевести загрузку в FAILED, пока этот запуск ею владеет."""
    try:
        with transaction.atomic():
            upload = _lock_active_run(upload_id, run_id)
            if upload is None:
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
    except BankStatementUpload.DoesNotExist:
        return


def _claim_run(
    upload_id: int,
    run_id: str,
) -> BankStatementUpload | None:
    """Lock the upload and start it only for the current run owner.

    The identifier is assigned before publication. A delivery with an older
    identifier, or one that arrives after cleanup or the retention deadline,
    gets ``None`` and must not write any run state.
    """
    with transaction.atomic():
        upload = (
            BankStatementUpload.objects.select_for_update()
            .select_related('account', 'user')
            .get(pk=upload_id)
        )
        if (
            upload.retention_cleaned_at is not None
            or upload.expires_at <= timezone.now()
        ):
            return None
        if upload.celery_task_id and upload.celery_task_id != run_id:
            return None
        upload.celery_task_id = run_id
        upload.status = BankStatementUpload.Status.PROCESSING
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
        return upload
