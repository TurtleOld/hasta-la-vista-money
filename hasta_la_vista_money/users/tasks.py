"""Celery tasks for user-related async operations."""

import logging

from celery import shared_task
from django.db import transaction
from django.db.models import F

from config.containers import ApplicationContainer
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
from hasta_la_vista_money.users.services.pii_stripper import strip_pii

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def process_bank_statement_task(
    self: shared_task,  # type: ignore[valid-type]
    upload_id: int,
) -> dict[str, int]:
    """Обработать PDF-выписку в фоне: импортировать транзакции и сверить баланс.

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
        _initialize_upload(upload, self)

        classifier = ApplicationContainer().users.category_classifier()

        logger.info('Processing upload: %s', upload.pdf_file.path)
        parser = BankStatementParser(upload.pdf_file.path)
        parse_result = parser.parse()
        transactions = parse_result.transactions

        upload.total_transactions = len(transactions)
        upload.save(update_fields=['total_transactions'])

        logger.info('Found %d transactions to process', len(transactions))

        existing_categories = list(
            Category.objects.filter(user=upload.user)
            .values_list('name', flat=True)
            .distinct(),
        )

        income_count, expense_count, skipped_count = _process_transactions(
            upload=upload,
            transactions=transactions,
            classifier=classifier,
            existing_categories=existing_categories,
        )

        upload.account.refresh_from_db(fields=['balance'])
        if parse_result.closing_balance is not None:
            upload.statement_closing_balance = parse_result.closing_balance
            upload.account_balance_after = upload.account.balance
            upload.balance_discrepancy = (
                parse_result.closing_balance - upload.account.balance
            )

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

        logger.info(
            'Completed: %d income, %d expenses, %d skipped, discrepancy=%s',
            income_count,
            expense_count,
            skipped_count,
            upload.balance_discrepancy,
        )

        return {
            'income_count': income_count,
            'expense_count': expense_count,
            'skipped_count': skipped_count,
            'total_count': income_count + expense_count,
        }

    except BankStatementUpload.DoesNotExist:
        logger.exception('Upload with id=%d not found', upload_id)
        raise

    except BankStatementParseError as e:
        logger.exception('Failed to parse bank statement')
        try:
            upload = BankStatementUpload.objects.get(id=upload_id)
            upload.status = BankStatementUpload.Status.FAILED
            upload.error_message = f'Ошибка парсинга: {e!s}'
            upload.save(update_fields=['status', 'error_message'])
        except BankStatementUpload.DoesNotExist:
            pass
        raise

    except Exception as e:
        logger.exception('Unexpected error processing bank statement')
        try:
            upload = BankStatementUpload.objects.get(id=upload_id)
            upload.status = BankStatementUpload.Status.FAILED
            upload.error_message = f'Непредвиденная ошибка: {e!s}'
            upload.save(update_fields=['status', 'error_message'])
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
    upload.save(update_fields=['status', 'celery_task_id', 'progress'])


def _process_transactions(
    upload: BankStatementUpload,
    transactions: list[dict],
    classifier,
    existing_categories: list[str],
) -> tuple[int, int, int]:
    """Создать транзакции из разобранных записей выписки.

    Args:
        upload: Запись загрузки для сохранения прогресса.
        transactions: Список разобранных операций из ``StatementParseResult``.
        classifier: Экземпляр ``CategoryClassifier`` для определения категории.
        existing_categories: Актуальный список категорий пользователя для LLM.

    Returns:
        Кортеж ``(income_count, expense_count, skipped_count)``.
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
                clean_desc = strip_pii(description)
                category_name = classifier.classify(
                    description=clean_desc,
                    transaction_type=type_value,
                    existing_categories=existing_categories,
                )
                if category_name not in existing_categories:
                    existing_categories.append(category_name)

                category, _ = Category.objects.get_or_create(
                    user=upload.user,
                    name=category_name[:250],
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
    """Проверить, не была ли операция уже импортирована.

    При наличии ``source_ref`` сначала ищет точное совпадение, затем
    делает откат к поиску по ``(account, user, type, amount, date)`` среди
    записей без ``source_ref`` (созданных до введения идентификаторов).
    Если найдена такая «legacy»-запись — проставляет ей ``source_ref``.

    Args:
        account: Счёт, к которому привязана операция.
        user: Пользователь-владелец.
        type_value: ``'income'`` или ``'expense'``.
        abs_amount: Абсолютное значение суммы операции.
        trans_date: Дата/время операции.
        source_ref: Идентификатор операции из выписки или ``None``.

    Returns:
        ``True`` если операция уже существует в базе, иначе ``False``.
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
