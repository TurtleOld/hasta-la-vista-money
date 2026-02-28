"""Celery tasks for user-related async operations."""

import logging

from celery import shared_task
from django.db import transaction
from django.db.models import F

from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income, IncomeCategory
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

        income_count, expense_count = _process_transactions(
            upload,
            transactions,
        )

        # Mark as completed
        upload.status = BankStatementUpload.Status.COMPLETED
        upload.progress = 100
        upload.save(update_fields=['status', 'progress'])

        logger.info(
            'Completed: %d income, %d expenses',
            income_count,
            expense_count,
        )

        return {
            'income_count': income_count,
            'expense_count': expense_count,
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
) -> tuple[int, int]:
    """Process transactions and create income/expense records.

    Args:
        upload: Upload instance.
        transactions: List of parsed transactions.

    Returns:
        Tuple of (income_count, expense_count).
    """
    income_count = 0
    expense_count = 0
    batch_size = 10
    total = len(transactions)

    for idx, trans in enumerate(transactions):
        with transaction.atomic():
            amount = trans['amount']
            description = trans['description']
            trans_date = trans['date']
            abs_amount = abs(amount)

            if amount > 0:
                category, _ = IncomeCategory.objects.get_or_create(
                    user=upload.user,
                    name=description[:250],
                )
                _, created = Income.objects.get_or_create(
                    user=upload.user,
                    account=upload.account,
                    category=category,
                    amount=abs_amount,
                    date=trans_date,
                )
                if created:
                    # Update account balance only for new records
                    Account.objects.filter(pk=upload.account.pk).update(
                        balance=F('balance') + abs_amount,
                    )
                    income_count += 1
            else:
                category, _ = ExpenseCategory.objects.get_or_create(
                    user=upload.user,
                    name=description[:250],
                )
                _, created = Expense.objects.get_or_create(
                    user=upload.user,
                    account=upload.account,
                    category=category,
                    amount=abs_amount,
                    date=trans_date,
                )
                if created:
                    # Update account balance only for new records
                    Account.objects.filter(pk=upload.account.pk).update(
                        balance=F('balance') - abs_amount,
                    )
                    expense_count += 1

        upload.processed_transactions = idx + 1
        upload.income_count = income_count
        upload.expense_count = expense_count
        upload.progress = int((idx + 1) / total * 100)

        # Save progress every batch or on last transaction
        if (idx + 1) % batch_size == 0 or idx == total - 1:
            upload.save(
                update_fields=[
                    'processed_transactions',
                    'income_count',
                    'expense_count',
                    'progress',
                ],
            )
            logger.info(
                'Progress: %d/%d transactions (%d%%)',
                idx + 1,
                total,
                upload.progress,
            )

    return income_count, expense_count
