"""Единый сервис импорта банковской выписки.

Инкапсулирует разбор PDF, дедупликацию (точный дубликат, вероятный дубль,
легаси-фолбэк), категоризацию и проводку финансового движения. Используется
Celery-задачей ``process_bank_statement_task``, которая остаётся единственным
прод-швом — в том числе для тестов (``process_bank_statement_task.apply(...)``)
— второй самостоятельной реализации импорта в проекте нет.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.utils import timezone

from hasta_la_vista_money.finance_account.services.balance_service import (
    BalanceService,
)
from hasta_la_vista_money.system.models import AuditOperationKind
from hasta_la_vista_money.system.services.audit_context import audit_operation
from hasta_la_vista_money.system.services.audit_statement_import import (
    record_statement_import_summary,
)
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
    BankStatementParser,
)
from hasta_la_vista_money.users.services.pii_stripper import strip_pii

if TYPE_CHECKING:
    from decimal import Decimal

    from hasta_la_vista_money.finance_account.models import Account
    from hasta_la_vista_money.users.services.category_classifier import (
        CategoryClassifier,
    )

logger = logging.getLogger(__name__)
FALLBACK_CATEGORY = 'Без категории'


@dataclass(frozen=True)
class StatementImportResult:
    """Итог одного прогона импорта банковской выписки.

    Attributes:
        income_count: Число созданных операций дохода.
        expense_count: Число созданных операций расхода.
        skipped_count: Число пропущенных операций (дубликат или
            вероятный дубль).
        closing_balance: Конечный остаток из выписки, если удалось извлечь.
    """

    income_count: int
    expense_count: int
    skipped_count: int
    closing_balance: Decimal | None


class BankStatementImportService:
    """Разбирает PDF-выписку и проводит по ней финансовые движения."""

    def __init__(self, classifier: CategoryClassifier) -> None:
        """Инициализировать сервис категоризатором операций."""
        self.classifier = classifier

    def import_statement(
        self,
        upload: BankStatementUpload,
    ) -> StatementImportResult:
        """Разобрать PDF выписки и создать по нему финансовые движения.

        Args:
            upload: Запись загрузки с уже сохранённым PDF-файлом.

        Returns:
            Итог прогона импорта.

        Raises:
            BankStatementParseError: Если PDF не удалось разобрать.
        """
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

        with audit_operation(kind=AuditOperationKind.STATEMENT_IMPORT):
            income_count, expense_count, skipped_count = (
                self._process_transactions(
                    upload=upload,
                    transactions=transactions,
                    existing_categories=existing_categories,
                )
            )

        return StatementImportResult(
            income_count=income_count,
            expense_count=expense_count,
            skipped_count=skipped_count,
            closing_balance=parse_result.closing_balance,
        )

    def _process_transactions(
        self,
        upload: BankStatementUpload,
        transactions: list[dict[str, Any]],
        existing_categories: list[str],
    ) -> tuple[int, int, int]:
        """Создать транзакции из разобранных записей выписки.

        Args:
            upload: Запись загрузки для сохранения прогресса.
            transactions: Список разобранных операций из
                ``StatementParseResult``.
            existing_categories: Актуальный список категорий пользователя
                для LLM.

        Returns:
            Кортеж ``(income_count, expense_count, skipped_count)``.
        """
        income_count = 0
        expense_count = 0
        skipped_count = 0
        batch_size = 10
        total = len(transactions)
        period_from: date | None = None
        period_to: date | None = None

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

                if self._is_exact_duplicate(
                    account=upload.account,
                    source_ref=source_ref,
                    source_file_hash=upload.file_hash,
                    source_row_position=row_position,
                ):
                    skipped_count += 1
                    created = False
                    candidate = None
                else:
                    candidates = self._find_probable_duplicates(
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
                    self._save_probable_duplicate(
                        upload=upload,
                        trans=trans,
                        candidates=candidates,
                        type_value=type_value,
                        row_position=row_position,
                        existing_categories=existing_categories,
                        match_calendar_date=source == 'ozon',
                    )
                    skipped_count += 1
                    created = False
                elif created and self._is_duplicate(
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
                        category_name = self._classify_category(
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
                    upload.account = BalanceService().apply_balance_delta(
                        upload.account,
                        balance_change,
                    )
                    if type_value == TransactionType.INCOME:
                        income_count += 1
                    else:
                        expense_count += 1
                    row_date = (
                        trans_date.date()
                        if isinstance(trans_date, datetime)
                        else trans_date
                    )
                    if period_from is None or row_date < period_from:
                        period_from = row_date
                    if period_to is None or row_date > period_to:
                        period_to = row_date

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

        record_statement_import_summary(
            user=upload.user,
            account=upload.account,
            created=income_count + expense_count,
            skipped_duplicates=skipped_count,
            period_from=period_from,
            period_to=period_to,
        )
        return income_count, expense_count, skipped_count

    def _is_exact_duplicate(
        self,
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
        self,
        *,
        upload: BankStatementUpload,
        trans: dict[str, Any],
        candidates: list[Transaction],
        type_value: str,
        row_position: int,
        existing_categories: list[str],
        match_calendar_date: bool,
    ) -> bool:
        clean_desc = strip_pii(str(trans['description']))
        category_name = trans.get('category_name')
        if category_name is None:
            category_name = self._classify_category(
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
                    description=self._candidate_description(candidate),
                    rank=rank,
                )
                for rank, candidate in enumerate(candidates)
            ],
            ignore_conflicts=True,
        )
        return True

    def _classify_category(
        self,
        description: str,
        type_value: str,
        existing_categories: list[str],
    ) -> str:
        try:
            return str(
                self.classifier.classify(
                    description=description,
                    transaction_type=type_value,
                    existing_categories=existing_categories,
                ),
            )
        except Exception:
            logger.warning('category_classifier_failed', exc_info=True)
            return FALLBACK_CATEGORY

    def _find_probable_duplicates(
        self,
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
                    self._candidate_description(candidate).casefold(),
                ).ratio(),
                candidate.pk,
            ),
        )

    def _candidate_description(self, candidate: Transaction) -> str:
        return candidate.description or str(candidate.category.name)

    def _is_duplicate(
        self,
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
        делает откат к поиску по ``(account, user, type, amount, date)``
        среди записей без ``source_ref`` (созданных до введения
        идентификаторов). Если найдена такая «legacy»-запись — проставляет
        ей ``source_ref``.

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
