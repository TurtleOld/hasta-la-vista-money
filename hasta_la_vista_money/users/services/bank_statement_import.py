"""Единый сервис импорта банковской выписки.

Инкапсулирует разбор PDF, дедупликацию (точный дубликат, вероятный дубль,
легаси-фолбэк), категоризацию и проводку финансового движения. Используется
Celery-задачей ``process_bank_statement_task``, которая остаётся единственным
прод-швом — в том числе для тестов (``process_bank_statement_task.apply(...)``)
— второй самостоятельной реализации импорта в проекте нет.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any

import structlog
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import TransferMoneyLog
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
    User,
)
from hasta_la_vista_money.users.repositories.transfer_matching import (
    find_mirroring_transfers,
    local_row_date,
)
from hasta_la_vista_money.users.services.bank_statement import (
    BankStatementParseError,
    BankStatementParser,
    RosDorBankRowKind,
)
from hasta_la_vista_money.users.services.pii_stripper import strip_pii

if TYPE_CHECKING:
    from decimal import Decimal

    from hasta_la_vista_money.finance_account.models import Account
    from hasta_la_vista_money.finance_account.repositories import (
        AccountRepository,
    )
    from hasta_la_vista_money.users.services.category_classifier import (
        CategoryClassifier,
    )

logger = structlog.get_logger(__name__)
FALLBACK_CATEGORY = 'Без категории'


@dataclass(frozen=True)
class StatementImportResult:
    """Итог одного прогона импорта банковской выписки.

    Attributes:
        income_count: Число созданных операций дохода.
        expense_count: Число созданных операций расхода.
        skipped_count: Число пропущенных операций (дубликат или
            вероятный дубль).
        needs_transfer_count: Число зачислений на кредитный счёт,
            сохранённых как непроведённые погашения.
        closing_balance: Конечный остаток из выписки, если удалось извлечь.
    """

    income_count: int
    expense_count: int
    skipped_count: int
    needs_transfer_count: int
    closing_balance: Decimal | None


@dataclass(frozen=True)
class ProbableDuplicate:
    """Movement already recorded that may mirror a statement row."""

    description: str
    movement: Transaction | TransferMoneyLog


class BankStatementImportService:
    """Разбирает PDF-выписку и проводит по ней финансовые движения."""

    def __init__(
        self,
        classifier: CategoryClassifier,
        account_repository: AccountRepository,
    ) -> None:
        """Инициализировать сервис категоризатором и репозиторием счетов."""
        self.classifier = classifier
        self.account_repository = account_repository

    def restart_if_stale(self, upload: BankStatementUpload) -> bool:
        """Вернуть упавшую или зависшую загрузку в очередь.

        Перезапускается FAILED-загрузка и PENDING/PROCESSING, не
        обновлявшаяся дольше ``STATEMENT_UPLOAD_STALE_MINUTES``. Переход
        условный (по статусу и ``updated_at``), поэтому из двух
        параллельных запросов перезапуск выигрывает только один.

        Returns:
            ``True``, если загрузку нужно поставить в очередь заново.
        """
        stale_after = timedelta(
            minutes=constants.STATEMENT_UPLOAD_STALE_MINUTES,
        )
        in_flight = {
            BankStatementUpload.Status.PENDING,
            BankStatementUpload.Status.PROCESSING,
        }
        if upload.status == BankStatementUpload.Status.FAILED:
            pass
        elif (
            upload.status not in in_flight
            or timezone.now() - upload.updated_at <= stale_after
        ):
            return False
        restarted = BankStatementUpload.objects.filter(
            pk=upload.pk,
            status=upload.status,
            updated_at=upload.updated_at,
        ).update(
            status=BankStatementUpload.Status.PENDING,
            error_message='',
            updated_at=timezone.now(),
        )
        if restarted:
            upload.refresh_from_db()
        return bool(restarted)

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
        logger.info(
            'bank_statement_import_started',
            upload_id=upload.pk,
            user_id=upload.user_id,
        )
        parser = BankStatementParser(upload.pdf_file.path)
        parse_result = parser.parse()
        transactions = parse_result.transactions
        if parse_result.account_number:
            with audit_operation(kind=AuditOperationKind.STATEMENT_IMPORT):
                self._match_account(upload, parse_result.account_number)

        upload.total_transactions = len(transactions)
        upload.save(update_fields=['total_transactions'])

        logger.info(
            'bank_statement_transactions_found',
            upload_id=upload.pk,
            transactions=len(transactions),
        )

        if parse_result.requires_markup:
            self._save_markup_rows(upload, transactions)
            return StatementImportResult(
                income_count=0,
                expense_count=0,
                skipped_count=upload.skipped_count,
                needs_transfer_count=0,
                closing_balance=parse_result.closing_balance,
            )

        existing_categories = list(
            Category.objects.filter(user=upload.user)
            .values_list('name', flat=True)
            .distinct(),
        )

        with audit_operation(kind=AuditOperationKind.STATEMENT_IMPORT):
            (
                income_count,
                expense_count,
                skipped_count,
                needs_transfer_count,
            ) = self._process_transactions(
                upload=upload,
                transactions=transactions,
                existing_categories=existing_categories,
            )

        return StatementImportResult(
            income_count=income_count,
            expense_count=expense_count,
            skipped_count=skipped_count,
            needs_transfer_count=needs_transfer_count,
            closing_balance=parse_result.closing_balance,
        )

    def _process_transactions(
        self,
        upload: BankStatementUpload,
        transactions: list[dict[str, Any]],
        existing_categories: list[str],
    ) -> tuple[int, int, int, int]:
        """Создать транзакции из разобранных записей выписки.

        Положительные строки кредитного счёта не становятся доходом:
        они сохраняются как непроведённые погашения (``needs_transfer``).
        Остальные строки проходят обычную дедупликацию и проводку.

        Args:
            upload: Запись загрузки для сохранения прогресса.
            transactions: Список разобранных операций из
                ``StatementParseResult``.
            existing_categories: Актуальный список категорий пользователя
                для LLM.

        Returns:
            Кортеж ``(income_count, expense_count, skipped_count,
            needs_transfer_count)``.
        """
        # Counters and cursor are saved atomically with each row, so a
        # rerun resumes where the previous run stopped.
        income_count = upload.income_count
        expense_count = upload.expense_count
        skipped_count = upload.skipped_count
        needs_transfer_count = upload.needs_transfer_count
        resume_from = upload.processed_transactions
        batch_size = 10
        total = len(transactions)
        period_from: date | None = None
        period_to: date | None = None

        for idx, trans in enumerate(transactions):
            if idx < resume_from:
                row_date = (
                    trans['date'].date()
                    if isinstance(trans['date'], datetime)
                    else trans['date']
                )
                period_from = min(period_from or row_date, row_date)
                period_to = max(period_to or row_date, row_date)
                continue
            amount = trans['amount']
            description = trans['description']
            trans_date = trans['date']
            source_ref = trans.get('source_ref')
            row_position = trans.get('row_position', idx)
            source = trans.get('source')
            abs_amount = abs(amount)
            is_credit_income = (
                amount > 0
                and upload.account.type_account
                in constants.CREDIT_ACCOUNT_TYPES
            )
            if amount > 0:
                type_value = TransactionType.INCOME
                balance_change = abs_amount
            else:
                type_value = TransactionType.EXPENSE
                balance_change = -abs_amount

            # The classifier is a network call: keep it out of the row
            # transaction so a slow model does not hold it open.
            category_name = trans.get('category_name')
            if (
                category_name is None
                and not is_credit_income
                and not self._is_exact_duplicate(
                    account=upload.account,
                    source_ref=source_ref,
                    source_file_hash=upload.file_hash,
                    source_row_position=row_position,
                )
            ):
                category_name = self._classify_category(
                    strip_pii(str(description)),
                    type_value,
                    existing_categories,
                )

            with transaction.atomic():
                if is_credit_income:
                    self._save_needs_transfer_row(
                        upload=upload,
                        trans=trans,
                        row_position=row_position,
                    )
                    needs_transfer_count += 1
                else:
                    # Unclassified only if the row stopped being a duplicate
                    # after the check above.
                    row_category = str(category_name or FALLBACK_CATEGORY)
                    candidates: list[ProbableDuplicate]
                    if self._is_exact_duplicate(
                        account=upload.account,
                        source_ref=source_ref,
                        source_file_hash=upload.file_hash,
                        source_row_position=row_position,
                    ):
                        skipped_count += 1
                        created = False
                        candidates = []
                    else:
                        candidates = self._rank_probable_candidates(
                            account=upload.account,
                            user=upload.user,
                            type_value=type_value,
                            abs_amount=abs_amount,
                            trans_date=trans_date,
                            match_calendar_date=source == 'ozon',
                            description=strip_pii(str(description)),
                            current_file_hash=upload.file_hash,
                        )
                        created = True
                    if candidates:
                        self._save_probable_duplicate(
                            upload=upload,
                            trans=trans,
                            candidates=candidates,
                            type_value=type_value,
                            row_position=row_position,
                            category_name=row_category,
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
                        if row_category not in existing_categories:
                            existing_categories.append(row_category)

                        category, _created_category = (
                            Category.objects.get_or_create(
                                user=upload.user,
                                name=row_category[
                                    : constants.TWO_HUNDRED_FIFTY
                                ],
                                type=type_value,
                            )
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
                        # The bank is the source of truth: no funds check.
                        upload.account = BalanceService().apply_balance_delta(
                            upload.account,
                            balance_change,
                            check_funds=False,
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
                upload.needs_transfer_count = needs_transfer_count
                upload.progress = int((idx + 1) / total * 100)
                upload.save(
                    update_fields=[
                        'processed_transactions',
                        'income_count',
                        'expense_count',
                        'skipped_count',
                        'needs_transfer_count',
                        'progress',
                        'updated_at',
                    ],
                )

            if (idx + 1) % batch_size == 0 or idx == total - 1:
                logger.info(
                    'bank_statement_import_progress',
                    upload_id=upload.pk,
                    processed=idx + 1,
                    total=total,
                    progress=upload.progress,
                )

        record_statement_import_summary(
            user=upload.user,
            account=upload.account,
            created=income_count + expense_count,
            skipped_duplicates=skipped_count,
            period_from=period_from,
            period_to=period_to,
        )
        return income_count, expense_count, skipped_count, needs_transfer_count

    def _match_account(
        self,
        upload: BankStatementUpload,
        account_number: str,
    ) -> None:
        """Pick the account by the statement number or record the number.

        Raises:
            BankStatementParseError: The selected account has another
                number, or the number cannot be recorded.
        """
        account = upload.account
        if account.account_number == account_number:
            return
        if account.account_number:
            raise BankStatementParseError(
                _(
                    'Номер счёта в выписке {number} не совпадает '
                    'с номером выбранного счёта.',
                ).format(number=account_number),
            )
        matched = self.account_repository.get_by_user_and_account_number(
            upload.user,
            account_number,
        )
        if matched is None:
            account.account_number = account_number
            try:
                with transaction.atomic():
                    account.save(update_fields=['account_number'])
            except IntegrityError as e:
                raise BankStatementParseError(
                    _('Номер счёта уже используется'),
                ) from e
            return
        if matched.is_archived or matched.is_deposit:
            raise BankStatementParseError(
                _('Архивный счёт или счёт вклада недоступен для импорта.'),
            )
        upload.account = matched
        try:
            with transaction.atomic():
                upload.save(update_fields=['account'])
        except IntegrityError as e:
            raise BankStatementParseError(
                _('Эта выписка уже была загружена.'),
            ) from e

    def _save_markup_rows(
        self,
        upload: BankStatementUpload,
        transactions: list[dict[str, Any]],
    ) -> None:
        """Save rows awaiting user markup; none of them is posted.

        Rows already known on the account, marked up or still awaiting
        markup, are skipped, so an overlapping period adds only new rows.
        """
        refs = [trans['source_ref'] for trans in transactions]
        with transaction.atomic():
            # Serialize overlapping uploads of one account.
            self.account_repository.get_by_ids_for_update({upload.account_id})
            created = self._create_markup_rows(upload, transactions, refs)
        upload.processed_transactions = len(transactions)
        upload.skipped_count = len(transactions) - created
        upload.progress = 100
        upload.save(
            update_fields=[
                'processed_transactions',
                'skipped_count',
                'progress',
                'updated_at',
            ],
        )

    def _create_markup_rows(
        self,
        upload: BankStatementUpload,
        transactions: list[dict[str, Any]],
        refs: list[str],
    ) -> int:
        known_refs = set(
            BankStatementRow.objects.filter(
                upload__account=upload.account,
                source_ref__in=refs,
            )
            .exclude(upload=upload)
            .exclude(decision=BankStatementRow.Decision.EXPIRED)
            .values_list('source_ref', flat=True),
        ) | set(
            Transaction.objects.filter(
                account=upload.account,
                source_ref__in=refs,
            ).values_list('source_ref', flat=True),
        )
        new_rows = {
            idx: trans
            for idx, trans in enumerate(transactions)
            if trans['source_ref'] not in known_refs
        }
        # A cancel of a debit from an earlier upload is an income to mark up.
        cancelled = _mutual_cancel_positions(new_rows)
        rows = [
            BankStatementRow(
                upload=upload,
                transaction_type=(
                    TransactionType.INCOME
                    if trans['amount'] > 0
                    else TransactionType.EXPENSE
                ),
                transaction_date=trans['date'],
                amount=abs(trans['amount']),
                description=strip_pii(str(trans['description']))[
                    : constants.TWO_HUNDRED_FIFTY
                ],
                source_ref=trans['source_ref'],
                source_row_position=idx,
                match_calendar_date=True,
                kind=str(trans['kind']),
                merchant_key=trans['merchant_key'] or '',
                counterparty_account=trans['counterparty_account'] or '',
                decision=(
                    BankStatementRow.Decision.MUTUAL_CANCEL
                    if idx in cancelled
                    else BankStatementRow.Decision.AWAITING_MARKUP
                ),
            )
            for idx, trans in new_rows.items()
        ]
        # A rerun of the same upload hits the per-upload row constraint.
        BankStatementRow.objects.bulk_create(rows, ignore_conflicts=True)
        return len(rows)

    def _save_needs_transfer_row(
        self,
        *,
        upload: BankStatementUpload,
        trans: dict[str, Any],
        row_position: int,
    ) -> None:
        """Save a credit-account credit as an unperformed repayment row."""
        BankStatementRow.objects.get_or_create(
            upload=upload,
            source_row_position=row_position,
            defaults={
                'transaction_type': TransactionType.INCOME,
                'transaction_date': trans['date'],
                'amount': abs(trans['amount']),
                'description': strip_pii(str(trans['description']))[:250],
                'source_ref': trans.get('source_ref') or None,
                'decision': BankStatementRow.Decision.NEEDS_TRANSFER,
            },
        )

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
        candidates: list[ProbableDuplicate],
        type_value: str,
        row_position: int,
        category_name: str,
        match_calendar_date: bool,
    ) -> bool:
        clean_desc = strip_pii(str(trans['description']))
        first_transaction = next(
            (
                candidate.movement
                for candidate in candidates
                if isinstance(candidate.movement, Transaction)
            ),
            None,
        )
        candidate_description = (
            str(first_transaction.category.name)
            if first_transaction is not None
            else candidates[0].description
        )
        row, _created = BankStatementRow.objects.get_or_create(
            upload=upload,
            source_row_position=row_position,
            defaults={
                'transaction_type': type_value,
                'transaction_date': trans['date'],
                'amount': abs(trans['amount']),
                'description': clean_desc,
                'candidate_description': candidate_description[
                    : constants.TWO_HUNDRED_FIFTY
                ],
                'suggested_category': category_name[
                    : constants.TWO_HUNDRED_FIFTY
                ],
                'source_ref': trans.get('source_ref') or None,
                'candidate': first_transaction,
                'match_calendar_date': match_calendar_date,
            },
        )
        BankStatementCandidate.objects.bulk_create(
            [
                BankStatementCandidate(
                    row=row,
                    transaction=(
                        candidate.movement
                        if isinstance(candidate.movement, Transaction)
                        else None
                    ),
                    transfer=(
                        candidate.movement
                        if isinstance(candidate.movement, TransferMoneyLog)
                        else None
                    ),
                    description=candidate.description[
                        : constants.TWO_HUNDRED_FIFTY
                    ],
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

    def _rank_probable_candidates(
        self,
        *,
        account: Account,
        user: User,
        type_value: str,
        abs_amount: Decimal,
        trans_date: datetime,
        match_calendar_date: bool,
        description: str,
        current_file_hash: str,
    ) -> list[ProbableDuplicate]:
        candidates = [
            ProbableDuplicate(
                description=self._candidate_description(transaction),
                movement=transaction,
            )
            for transaction in self._find_transaction_duplicates(
                account=account,
                user=user,
                type_value=type_value,
                abs_amount=abs_amount,
                trans_date=trans_date,
                match_calendar_date=match_calendar_date,
                description=description,
                current_file_hash=current_file_hash,
            )
        ]
        candidates.extend(
            ProbableDuplicate(
                description=self._transfer_candidate_description(transfer),
                movement=transfer,
            )
            for transfer in self._find_transfer_duplicates(
                account=account,
                user=user,
                type_value=type_value,
                abs_amount=abs_amount,
                trans_date=trans_date,
            )
        )
        return sorted(
            candidates,
            key=lambda candidate: (
                -SequenceMatcher(
                    None,
                    description.casefold(),
                    candidate.description.casefold(),
                ).ratio(),
                candidate.movement.pk,
            ),
        )

    def _find_transfer_duplicates(
        self,
        *,
        account: Account,
        user: User,
        type_value: str,
        abs_amount: Decimal,
        trans_date: datetime,
    ) -> list[TransferMoneyLog]:
        """Return transfers mirroring the statement row within one day."""
        return list(
            find_mirroring_transfers(
                account=account,
                user=user,
                transaction_type=type_value,
                amount=abs_amount,
                row_date=local_row_date(trans_date),
            ),
        )

    def _transfer_candidate_description(
        self,
        transfer: TransferMoneyLog,
    ) -> str:
        source = (
            transfer.from_account.name_account
            if transfer.from_account is not None
            else ''
        )
        target = (
            transfer.to_account.name_account
            if transfer.to_account is not None
            else ''
        )
        return (
            _('Перевод: {source} → {target}')
            .format(
                source=source,
                target=target,
            )
            .strip(' →')[: constants.TWO_HUNDRED_FIFTY]
        )

    def _find_transaction_duplicates(
        self,
        *,
        account: Account,
        user: User,
        type_value: str,
        abs_amount: Decimal,
        trans_date: datetime,
        match_calendar_date: bool,
        description: str,
        current_file_hash: str,
    ) -> list[Transaction]:
        queryset = Transaction.objects.without_adjustments().filter(
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
            legacy_queryset = Transaction.objects.without_adjustments().filter(
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


def _mutual_cancel_positions(rows: dict[int, dict[str, Any]]) -> set[int]:
    """Pair each cancel with a debit of the same device owner and amount."""
    debits: dict[tuple[str, Decimal], list[int]] = {}
    for idx, trans in rows.items():
        if trans['kind'] == RosDorBankRowKind.CARD and trans['amount'] < 0:
            debits.setdefault(
                (trans['description'], -trans['amount']),
                [],
            ).append(idx)
    positions: set[int] = set()
    for idx, trans in rows.items():
        if trans['kind'] != RosDorBankRowKind.CANCEL:
            continue
        matches = debits.get((trans['description'], trans['amount']))
        if matches:
            positions |= {matches.pop(0), idx}
    return positions
