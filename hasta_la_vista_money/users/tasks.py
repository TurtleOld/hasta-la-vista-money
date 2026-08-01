"""Celery tasks for user-related async operations."""

import logging
from datetime import datetime
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any

from celery import shared_task
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import (
    BankStatementCandidate,
    BankStatementRow,
    BankStatementUpload,
)
from hasta_la_vista_money.users.services.bank_statement import (
    BankStatementParseError,
    BankStatementParser,
)
from hasta_la_vista_money.users.services.bank_statement_reconciliation import (
    BankStatementReconciliationService,
)
from hasta_la_vista_money.users.services.category_classifier import (
    CategoryClassifier,
)
from hasta_la_vista_money.users.services.pii_stripper import strip_pii

logger = logging.getLogger(__name__)
FALLBACK_CATEGORY = 'Без категории'


@shared_task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def process_bank_statement_task(
    self: Any,
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


def _process_transactions(
    upload: BankStatementUpload,
    transactions: list[dict[str, Any]],
    classifier: CategoryClassifier,
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
            row_position = trans.get('row_position', idx)
            source = trans.get('source')
            abs_amount = abs(amount)

            if amount > 0:
                type_value = TransactionType.INCOME
                balance_change = abs_amount
            else:
                type_value = TransactionType.EXPENSE
                balance_change = -abs_amount

            if _is_exact_duplicate(
                account=upload.account,
                source_ref=source_ref,
                source_file_hash=upload.file_hash,
                source_row_position=row_position,
            ):
                skipped_count += 1
                created = False
                candidate = None
            else:
                candidates = _find_probable_duplicates(
                    account=upload.account,
                    user=upload.user,
                    type_value=type_value,
                    abs_amount=abs_amount,
                    trans_date=trans_date,
                    match_calendar_date=source == 'ozon',
                    description=strip_pii(str(description)),
                    current_file_hash=upload.file_hash,
                )
                candidate = candidates[0] if candidates else None
                created = True
            if candidate is not None:
                _save_probable_duplicate(
                    upload=upload,
                    trans=trans,
                    candidates=candidates,
                    type_value=type_value,
                    row_position=row_position,
                    classifier=classifier,
                    existing_categories=existing_categories,
                    match_calendar_date=source == 'ozon',
                )
                skipped_count += 1
                created = False
            elif created and _is_duplicate(
                account=upload.account,
                user=upload.user,
                type_value=type_value,
                abs_amount=abs_amount,
                trans_date=trans_date,
                source_ref=source_ref,
                source_file_hash=upload.file_hash,
                source_row_position=row_position,
                match_calendar_date=source == 'ozon',
            ):
                skipped_count += 1
                created = False
            elif created:
                category_name = trans.get('category_name')
                if category_name is None:
                    clean_desc = strip_pii(description)
                    category_name = _classify_category(
                        classifier,
                        clean_desc,
                        type_value,
                        existing_categories,
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
                    description=strip_pii(str(description))[:250],
                    source_ref=source_ref or None,
                    source_file_hash=(
                        upload.file_hash if not source_ref else None
                    ),
                    source_row_position=(
                        row_position if not source_ref else None
                    ),
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


def _is_exact_duplicate(
    *,
    account: Account,
    source_ref: str | None,
    source_file_hash: str,
    source_row_position: int,
) -> bool:
    if source_ref:
        return bool(
            Transaction.objects.filter(
                account=account,
                source_ref=source_ref,
            ).exists(),
        )
    return bool(
        Transaction.objects.filter(
            account=account,
            source_file_hash=source_file_hash,
            source_row_position=source_row_position,
        ).exists(),
    )


def _save_probable_duplicate(
    *,
    upload: BankStatementUpload,
    trans: dict[str, Any],
    candidates: list[Transaction],
    type_value: str,
    row_position: int,
    classifier: CategoryClassifier,
    existing_categories: list[str],
    match_calendar_date: bool,
) -> bool:
    clean_desc = strip_pii(str(trans['description']))
    category_name = trans.get('category_name')
    if category_name is None:
        category_name = _classify_category(
            classifier,
            clean_desc,
            type_value,
            existing_categories,
        )
    row, _ = BankStatementRow.objects.get_or_create(
        upload=upload,
        source_row_position=row_position,
        defaults={
            'transaction_type': type_value,
            'transaction_date': trans['date'],
            'amount': abs(trans['amount']),
            'description': clean_desc,
            'candidate_description': str(candidates[0].category.name),
            'suggested_category': str(category_name)[:250],
            'source_ref': trans.get('source_ref') or None,
            'candidate': candidates[0],
            'match_calendar_date': match_calendar_date,
        },
    )
    BankStatementCandidate.objects.bulk_create(
        [
            BankStatementCandidate(
                row=row,
                transaction=candidate,
                description=_candidate_description(candidate),
                rank=rank,
            )
            for rank, candidate in enumerate(candidates)
        ],
        ignore_conflicts=True,
    )
    return True


def _classify_category(
    classifier: CategoryClassifier,
    description: str,
    type_value: str,
    existing_categories: list[str],
) -> str:
    try:
        return str(
            classifier.classify(
                description=description,
                transaction_type=type_value,
                existing_categories=existing_categories,
            ),
        )
    except Exception:
        logger.warning('category_classifier_failed', exc_info=True)
        return FALLBACK_CATEGORY


def _find_probable_duplicates(
    *,
    account: Account,
    user: Any,
    type_value: str,
    abs_amount: Decimal,
    trans_date: datetime,
    match_calendar_date: bool,
    description: str,
    current_file_hash: str,
) -> list[Transaction]:
    queryset = Transaction.objects.filter(
        account=account,
        user=user,
        type=type_value,
        amount=abs_amount,
    )
    if current_file_hash:
        queryset = queryset.exclude(source_file_hash=current_file_hash)
    if match_calendar_date:
        queryset = queryset.filter(
            date__date=timezone.localtime(trans_date).date(),
        )
    else:
        queryset = queryset.filter(date=trans_date)
    candidates = list(
        queryset.select_related('category').order_by('date', 'pk'),
    )
    return sorted(
        candidates,
        key=lambda candidate: (
            -SequenceMatcher(
                None,
                description.casefold(),
                _candidate_description(candidate).casefold(),
            ).ratio(),
            candidate.pk,
        ),
    )


def _candidate_description(candidate: Transaction) -> str:
    return candidate.description or str(candidate.category.name)


def _is_duplicate(
    *,
    account: Account,
    user: Any,
    type_value: str,
    abs_amount: Decimal,
    trans_date: datetime,
    source_ref: str | None,
    source_file_hash: str,
    source_row_position: int,
    match_calendar_date: bool = False,
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
        legacy_queryset = Transaction.objects.filter(
            account=account,
            user=user,
            type=type_value,
            amount=abs_amount,
            source_ref__isnull=True,
        )
        if match_calendar_date:
            legacy_queryset = legacy_queryset.filter(
                date__date=timezone.localtime(trans_date).date(),
            )
        else:
            legacy_queryset = legacy_queryset.filter(date=trans_date)
        legacy = legacy_queryset.order_by('date', 'pk').first()
        if legacy is not None:
            legacy.source_ref = source_ref
            legacy.save(update_fields=['source_ref'])
            return True
        return False
    return bool(
        Transaction.objects.filter(
            account=account,
            source_file_hash=source_file_hash,
            source_row_position=source_row_position,
        ).exists(),
    )
