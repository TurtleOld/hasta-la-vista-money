"""Celery tasks for user-related async operations."""

import logging

from celery import shared_task
from django.db import transaction
from django.db.models import F

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import BankStatementUpload
from hasta_la_vista_money.users.services.bank_statement import (
    BankStatementParseError,
    BankStatementParser,
)

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def process_bank_statement_task(
    self: shared_task,  # type: ignore[valid-type]
    upload_id: int,
) -> dict[str, int]:
    """Process bank statement PDF in background.

    Args:
        self: Celery task instance.
        upload_id: ID of the BankStatementUpload instance.

    Returns:
        Dictionary with counts of created transactions.

    Raises:
        BankStatementParseError: If parsing fails.
    """
    logger.info(
        'Starting bank statement processing task for upload_id=%d',
        upload_id,
    )

    try:
        upload = BankStatementUpload.objects.get(id=upload_id)
        _initialize_upload(upload, self)

        logger.info('Processing upload: %s', upload.pdf_file.path)

        # Parse the PDF
        parser = BankStatementParser(upload.pdf_file.path)
        transactions = parser.parse()

        upload.total_transactions = len(transactions)
        upload.save(update_fields=['total_transactions'])

        logger.info('Found %d transactions to process', len(transactions))

        income_count, expense_count, skipped_count = _process_transactions(
            upload,
            transactions,
        )

        # Mark as completed
        upload.status = BankStatementUpload.Status.COMPLETED
        upload.progress = 100
        upload.save(update_fields=['status', 'progress'])

        logger.info(
            'Completed: %d income, %d expenses, %d skipped',
            income_count,
            expense_count,
            skipped_count,
        )

        return {
            'income_count': income_count,
            'expense_count': expense_count,
            'skipped_count': skipped_count,
            'total_count': income_count + expense_count,
        }

    except BankStatementUpload.DoesNotExist:
        error_msg = f'Upload with id={upload_id} not found'
        logger.exception(error_msg)
        raise

    except BankStatementParseError as e:
        logger.exception('Failed to parse bank statement')
        try:
            upload = BankStatementUpload.objects.get(id=upload_id)
            upload.status = BankStatementUpload.Status.FAILED
            upload.error_message = f'Ошибка парсинга: {e!s}'
            upload.save(update_fields=['status', 'error_message'])
        except BankStatementUpload.DoesNotExist:
            logger.warning('Upload record not found for error handling')
        raise

    except Exception as e:
        logger.exception('Unexpected error processing bank statement')
        try:
            upload = BankStatementUpload.objects.get(id=upload_id)
            upload.status = BankStatementUpload.Status.FAILED
            upload.error_message = f'Непредвиденная ошибка: {e!s}'
            upload.save(update_fields=['status', 'error_message'])
        except BankStatementUpload.DoesNotExist:
            logger.warning('Upload record not found for error handling')
        # Retry the task
        raise self.retry(exc=e, countdown=60) from e


def _initialize_upload(
    upload: BankStatementUpload,
    task: shared_task,
) -> None:
    """Initialize upload record for processing.

    Args:
        upload: Upload instance to initialize.
        task: Celery task instance.
    """
    upload.status = BankStatementUpload.Status.PROCESSING
    upload.celery_task_id = task.request.id
    upload.progress = 0
    upload.save(update_fields=['status', 'celery_task_id', 'progress'])


def _process_transactions(
    upload: BankStatementUpload,
    transactions: list[dict],
) -> tuple[int, int, int]:
    """Process transactions and create income/expense records.

    Returns:
        Tuple of (income_count, expense_count, skipped_count).
    """
    income_count = 0
    expense_count = 0
    skipped_count = 0
    batch_size = 10
    total = len(transactions)

    for idx, trans in enumerate(transactions):
        with transaction.atomic():
            amount = trans['amount']
            description = trans['description']
            trans_date = trans['date']
            source_ref = trans.get('source_ref')
            abs_amount = abs(amount)

            if amount > 0:
                type_value = TransactionType.INCOME
                balance_change = abs_amount
            else:
                type_value = TransactionType.EXPENSE
                balance_change = -abs_amount

            if _is_duplicate(
                account=upload.account,
                user=upload.user,
                type_value=type_value,
                abs_amount=abs_amount,
                trans_date=trans_date,
                source_ref=source_ref,
            ):
                skipped_count += 1
                created = False
            else:
                category, _ = Category.objects.get_or_create(
                    user=upload.user,
                    name=description[:250],
                    type=type_value,
                )
                Transaction.objects.create(
                    user=upload.user,
                    account=upload.account,
                    category=category,
                    type=type_value,
                    amount=abs_amount,
                    date=trans_date,
                    source_ref=source_ref or None,
                )
                created = True

            if created:
                Account.objects.filter(pk=upload.account.pk).update(
                    balance=F('balance') + balance_change,
                )
                if type_value == TransactionType.INCOME:
                    income_count += 1
                else:
                    expense_count += 1

        upload.processed_transactions = idx + 1
        upload.income_count = income_count
        upload.expense_count = expense_count
        upload.skipped_count = skipped_count
        upload.progress = int((idx + 1) / total * 100)

        # Save progress every batch or on last transaction
        if (idx + 1) % batch_size == 0 or idx == total - 1:
            upload.save(
                update_fields=[
                    'processed_transactions',
                    'income_count',
                    'expense_count',
                    'skipped_count',
                    'progress',
                ],
            )
            logger.info(
                'Progress: %d/%d transactions (%d%%)',
                idx + 1,
                total,
                upload.progress,
            )

    return income_count, expense_count, skipped_count


def _is_duplicate(
    *,
    account: Account,
    user,
    type_value: str,
    abs_amount,
    trans_date,
    source_ref: str | None,
) -> bool:
    """Return True if this transaction has already been imported.

    When ``source_ref`` is provided we first look for an exact match. If
    none is found we additionally fall back to ``(account, user, type,
    amount, date)`` against legacy records that have ``source_ref IS NULL``
    (created before per-operation refs were stored). When such a legacy
    record is found we backfill its ``source_ref`` so that subsequent
    imports match it directly, preventing duplicates.
    """
    if source_ref:
        if Transaction.objects.filter(
            account=account,
            source_ref=source_ref,
        ).exists():
            return True
        legacy = Transaction.objects.filter(
            account=account,
            user=user,
            type=type_value,
            amount=abs_amount,
            date=trans_date,
            source_ref__isnull=True,
        ).first()
        if legacy is not None:
            legacy.source_ref = source_ref
            legacy.save(update_fields=['source_ref'])
            return True
        return False
    return Transaction.objects.filter(
        account=account,
        user=user,
        type=type_value,
        amount=abs_amount,
        date=trans_date,
        source_ref__isnull=True,
    ).exists()
