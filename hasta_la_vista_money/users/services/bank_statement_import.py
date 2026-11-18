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
from typing import TYPE_CHECKING, Any, Final

import structlog
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

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
from hasta_la_vista_money.users.services.bank_statement_reconciliation import (
    BankStatementReconciliationService,
)
from hasta_la_vista_money.users.services.pii_stripper import strip_pii
from hasta_la_vista_money.users.services.statement_identity import (
    IncomingStatementIdentity,
    StatementIdentityConflictError,
    StatementIdentityService,
)

if TYPE_CHECKING:
    from decimal import Decimal

    from django.utils.functional import Promise

    from hasta_la_vista_money.finance_account.models import Account
    from hasta_la_vista_money.finance_account.repositories import (
        AccountRepository,
    )
    from hasta_la_vista_money.users.repositories.statement_identity_repository import (  # noqa: E501
        StatementIdentityRepository,
    )
    from hasta_la_vista_money.users.services.category_classifier import (
        CategoryClassifier,
    )

logger = structlog.get_logger(__name__)
FALLBACK_CATEGORY = 'Без категории'


GENERATION_CURRENT: Final = 'current'
GENERATION_EXPIRED: Final = 'expired'
GENERATION_REPLACED: Final = 'replaced'
GENERATION_BUSY: Final = 'busy'
GENERATION_STARTED: Final = 'started'

REUPLOAD_REQUIRED_MESSAGE: Final[Promise] = _(
    'Данные выписки истекли. Загрузите выписку повторно.',
)


class StatementGenerationExpiredError(Exception):
    """Parsed work belongs to a cleaned or replaced upload generation."""


@dataclass(frozen=True)
class StatementGeneration:
    """Upload generation captured before parsing the statement."""

    file_hash: str
    pdf_name: str
    expires_at: datetime
    retention_cleaned_at: datetime | None


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
        identity_service: StatementIdentityService,
        identity_repository: StatementIdentityRepository,
    ) -> None:
        """Инициализировать сервис категоризатором и репозиторием счетов."""
        self.classifier = classifier
        self.account_repository = account_repository
        self.identity_service = identity_service
        self.identity_repository = identity_repository

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
        generation: StatementGeneration | None = None,
    ) -> StatementImportResult:
        """Разобрать PDF выписки и создать по нему финансовые движения.

        Args:
            upload: Запись загрузки с уже сохранённым PDF-файлом.
            generation: Поколение, зафиксированное вызывающим до запуска.

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
        generation = generation or self.capture_generation(upload)
        parser = BankStatementParser(upload.pdf_file.path)
        parse_result = parser.parse()
        transactions = parse_result.transactions
        if parse_result.account_number:
            with audit_operation(kind=AuditOperationKind.STATEMENT_IMPORT):
                self._match_account(upload, parse_result.account_number)
        bank_code = self._resolve_bank_code(
            upload,
            parse_result.bank_code,
            generation,
            len(transactions),
        )

        logger.info(
            'bank_statement_transactions_found',
            upload_id=upload.pk,
            transactions=len(transactions),
        )

        if parse_result.requires_markup:
            self._save_markup_rows(
                upload,
                transactions,
                bank_code,
                generation,
            )
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
                bank_code=bank_code,
                generation=generation,
            )

        return StatementImportResult(
            income_count=income_count,
            expense_count=expense_count,
            skipped_count=skipped_count,
            needs_transfer_count=needs_transfer_count,
            closing_balance=parse_result.closing_balance,
        )

    @staticmethod
    def capture_generation(
        upload: BankStatementUpload,
    ) -> StatementGeneration:
        """Record the upload generation the parse is allowed to touch."""
        return StatementGeneration(
            file_hash=upload.file_hash,
            pdf_name=upload.pdf_file.name or '',
            expires_at=upload.expires_at,
            retention_cleaned_at=upload.retention_cleaned_at,
        )

    @staticmethod
    def generation_state(
        upload: BankStatementUpload,
        generation: StatementGeneration,
    ) -> str:
        """Classify the upload against the generation captured before parse.

        A cleanup keeps the file hash and deadline but clears the PDF and
        sets the retention marker; that is the same generation expiring.
        Any change to the hash, deadline or a renewed file is a replacement.
        """
        if (
            upload.file_hash != generation.file_hash
            or upload.expires_at != generation.expires_at
        ):
            return_state = GENERATION_REPLACED
        elif upload.retention_cleaned_at != generation.retention_cleaned_at:
            if (
                generation.retention_cleaned_at is None
                and upload.retention_cleaned_at is not None
                and not upload.pdf_file.name
            ):
                return_state = GENERATION_EXPIRED
            else:
                return_state = GENERATION_REPLACED
        elif (upload.pdf_file.name or '') != generation.pdf_name:
            if (
                generation.pdf_name
                and not upload.pdf_file.name
                and upload.retention_cleaned_at is not None
            ):
                return_state = GENERATION_EXPIRED
            else:
                return_state = GENERATION_REPLACED
        elif upload.expires_at <= timezone.now():
            return_state = GENERATION_EXPIRED
        else:
            return_state = GENERATION_CURRENT
        return return_state

    @classmethod
    def _assert_generation(
        cls,
        upload: BankStatementUpload,
        generation: StatementGeneration,
    ) -> None:
        """Reject parsed work that outlived its upload generation."""
        if cls.generation_state(upload, generation) != GENERATION_CURRENT:
            raise StatementGenerationExpiredError('upload generation changed')

    def start_upload(
        self,
        upload_id: int,
        generation: StatementGeneration,
        task_id: str,
    ) -> str:
        """Move the upload to PROCESSING only for its current generation.

        Returns ``started``, ``expired``, ``replaced`` or ``busy``. A foreign
        active task id keeps its ownership; a cleaned/renewed generation is
        never overwritten.
        """
        with transaction.atomic():
            account_id = self.identity_repository.upload_account_id(
                upload_id,
            )
            if account_id is None:
                return GENERATION_REPLACED
            self.account_repository.get_by_ids_for_update({account_id})
            locked = self.identity_repository.lock_upload(upload_id)
            if locked is None:
                return GENERATION_REPLACED
            state = self.generation_state(locked, generation)
            if state != GENERATION_CURRENT:
                return state
            if (
                locked.status == BankStatementUpload.Status.PROCESSING
                and locked.celery_task_id
                and locked.celery_task_id != task_id
            ):
                return GENERATION_BUSY
            locked.status = BankStatementUpload.Status.PROCESSING
            locked.celery_task_id = task_id
            locked.failed_count = 0
            locked.error_message = ''
            self.identity_repository.save_upload_fields(
                locked,
                [
                    'status',
                    'celery_task_id',
                    'failed_count',
                    'error_message',
                    'updated_at',
                ],
            )
        return GENERATION_STARTED

    def resolve_expired_generation(
        self,
        upload_id: int,
        generation: StatementGeneration,
        task_id: str | None = None,
    ) -> str:
        """Record a truthful reupload terminal state for this generation.

        A replaced generation is left completely untouched. An expired or
        partially cleaned same generation becomes FAILED with a safe reason;
        bank sums are never restored and already posted money is preserved.
        Any different task owner keeps its state, including PROCESSING.
        """
        with transaction.atomic():
            account_id = self.identity_repository.upload_account_id(
                upload_id,
            )
            if account_id is None:
                return GENERATION_REPLACED
            self.account_repository.get_by_ids_for_update({account_id})
            locked = self.identity_repository.lock_upload(upload_id)
            if locked is None:
                return GENERATION_REPLACED
            state = self.generation_state(locked, generation)
            if state == GENERATION_REPLACED:
                return state
            if (
                task_id
                and locked.celery_task_id
                and locked.celery_task_id != task_id
            ):
                return state
            self.identity_repository.save_failed_upload(
                locked,
                str(REUPLOAD_REQUIRED_MESSAGE),
            )
            return state

    def mark_failure_if_current(
        self,
        upload_id: int,
        generation: StatementGeneration,
        task_id: str,
        message: str,
    ) -> str:
        """Record a failed run only while it still owns the generation.

        Generation state, task ownership and the write share one
        transaction under the account and upload locks, so a renewal
        cannot slip between the check and the write. A replaced
        generation or a newer task is left untouched; cleaned data gets
        only the safe reupload reason, never the raw parser error.
        """
        with transaction.atomic():
            account_id = self.identity_repository.upload_account_id(
                upload_id,
            )
            if account_id is None:
                return GENERATION_REPLACED
            self.account_repository.get_by_ids_for_update({account_id})
            locked = self.identity_repository.lock_upload(upload_id)
            if locked is None:
                return GENERATION_REPLACED
            state = self.generation_state(locked, generation)
            if state == GENERATION_REPLACED:
                return state
            if (
                task_id
                and locked.celery_task_id
                and locked.celery_task_id != task_id
            ):
                return state
            self.identity_repository.save_failed_upload(
                locked,
                (
                    str(REUPLOAD_REQUIRED_MESSAGE)
                    if state == GENERATION_EXPIRED
                    else message
                ),
            )
            return state

    def finalize_import(
        self,
        upload: BankStatementUpload,
        generation: StatementGeneration,
        *,
        closing_balance: Decimal | None,
    ) -> str:
        """Write status and bank sums only for the parsed generation.

        The account and upload are locked in the agreed order and the
        generation is checked again. A cleanup between the last row and
        this save leaves the cleaned fields untouched.
        """
        with transaction.atomic():
            accounts = self.account_repository.get_by_ids_for_update(
                {upload.account_id},
            )
            account = accounts[upload.account_id]
            locked = self.identity_repository.lock_upload(upload.pk)
            if locked is None:
                return GENERATION_REPLACED
            state = self.generation_state(locked, generation)
            if state != GENERATION_CURRENT:
                return state
            awaiting_markup = self.identity_repository.has_upload_rows(
                locked.pk,
                [
                    BankStatementRow.Decision.AWAITING_MARKUP,
                    BankStatementRow.Decision.DEFERRED,
                ],
            )
            has_pending = self.identity_repository.has_upload_rows(
                locked.pk,
                [BankStatementRow.Decision.PENDING],
            )
            has_parse_error = self.identity_repository.has_upload_rows(
                locked.pk,
                [BankStatementRow.Decision.PARSE_ERROR],
            )
            fields = ['progress', 'status', 'updated_at']
            if closing_balance is not None:
                locked.statement_closing_balance = closing_balance
                fields.append('statement_closing_balance')
            BankStatementReconciliationService.refresh_outcome_counts(locked)
            if (
                closing_balance is not None
                and not awaiting_markup
                and not has_parse_error
            ):
                locked.account_balance_after = account.balance
                locked.balance_discrepancy = closing_balance - account.balance
                fields += ['account_balance_after', 'balance_discrepancy']
            locked.progress = 100
            if awaiting_markup or has_pending or has_parse_error:
                locked.status = BankStatementUpload.Status.AWAITING_CONFIRMATION
            else:
                locked.status = BankStatementUpload.Status.COMPLETED
            self.identity_repository.save_upload_fields(
                locked,
                list(dict.fromkeys(fields)),
            )
            return GENERATION_CURRENT

    def _assert_row_generation(
        self,
        upload: BankStatementUpload,
        generation: StatementGeneration,
        source_row_position: int,
    ) -> None:
        """Reject a row whose stored details were cleaned while parsing."""
        self._assert_generation(upload, generation)
        if BankStatementRow.objects.filter(
            upload=upload,
            source_row_position=source_row_position,
            data_cleaned_at__isnull=False,
        ).exists():
            raise StatementGenerationExpiredError('row data cleaned')

    def _resolve_bank_code(
        self,
        upload: BankStatementUpload,
        parsed_bank_code: str | None,
        generation: StatementGeneration,
        total_transactions: int,
    ) -> str | None:
        """Freeze the parser's bank snapshot on the upload under its lock.

        The account is locked before the upload, matching the agreed lock
        order. A different parser result never overwrites the snapshot and
        a cleaned generation never receives new provenance or progress.

        Raises:
            BankStatementParseError: The parser contradicts the snapshot.
            StatementGenerationExpiredError: The upload generation changed.
        """
        try:
            with transaction.atomic():
                self.account_repository.get_by_ids_for_update(
                    {upload.account_id},
                )
                locked = BankStatementUpload.objects.select_for_update().get(
                    pk=upload.pk,
                )
                self._assert_generation(locked, generation)
                bank_code = self.identity_service.resolve_bank_code(
                    locked,
                    parsed_bank_code,
                )
                locked.total_transactions = total_transactions
                locked.save(update_fields=['total_transactions'])
                upload.source_bank_code = locked.source_bank_code
                upload.total_transactions = total_transactions
                return bank_code
        except StatementIdentityConflictError as error:
            raise BankStatementParseError(
                _(
                    'Банк в повторно разобранной выписке не совпадает '
                    'с сохранённым банком загрузки. Требуется ручная '
                    'проверка.',
                ),
            ) from error

    def _process_transactions(
        self,
        upload: BankStatementUpload,
        transactions: list[dict[str, Any]],
        existing_categories: list[str],
        bank_code: str | None,
        generation: StatementGeneration,
    ) -> tuple[int, int, int, int]:
        """Создать транзакции из разобранных записей выписки.

        Положительные строки кредитного счёта не становятся доходом:
        они сохраняются как непроведённые погашения (``needs_transfer``).
        Остальные строки проходят проверку идентичности и дедупликацию.

        Args:
            upload: Запись загрузки для сохранения прогресса.
            transactions: Список разобранных операций из
                ``StatementParseResult``.
            existing_categories: Актуальный список категорий пользователя
                для LLM.
            bank_code: Банк, выбранный парсером при первой загрузке.
            generation: Поколение загрузки, зафиксированное до разбора.

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
                and not self._precheck_blocks_posting(
                    upload=upload,
                    source_ref=source_ref,
                    row_position=row_position,
                    bank_code=bank_code,
                )
            ):
                category_name = self._classify_category(
                    strip_pii(str(description)),
                    type_value,
                    existing_categories,
                )

            with transaction.atomic():
                # Account before upload and row: the shared lock order.
                self.account_repository.get_by_ids_for_update(
                    {upload.account_id},
                )
                locked_upload = (
                    BankStatementUpload.objects.select_for_update().get(
                        pk=upload.pk,
                    )
                )
                self._assert_row_generation(
                    locked_upload,
                    generation,
                    row_position,
                )
                identity = self.identity_service.classify_incoming(
                    account_id=upload.account_id,
                    bank_code=bank_code,
                    source_ref=source_ref,
                    trusted_reference=self.identity_service.reference_is_trusted(
                        bank_code,
                        source_ref,
                    ),
                    exclude_upload_id=upload.pk,
                )
                same_file_duplicate = self.identity_service.same_file_posted(
                    account_id=upload.account_id,
                    source_file_hash=upload.file_hash,
                    source_row_position=row_position,
                )
                if is_credit_income:
                    if same_file_duplicate or identity.exact_duplicate:
                        skipped_count += 1
                    else:
                        self._save_needs_transfer_row(
                            upload=upload,
                            trans=trans,
                            row_position=row_position,
                            identity=identity,
                        )
                        needs_transfer_count += 1
                else:
                    # Unclassified only if the row stopped being a duplicate
                    # after the check above.
                    row_category = str(category_name or FALLBACK_CATEGORY)
                    created = False
                    if same_file_duplicate or identity.exact_duplicate:
                        skipped_count += 1
                    elif identity.manual:
                        self._save_manual_row(
                            upload=upload,
                            trans=trans,
                            type_value=type_value,
                            row_position=row_position,
                            identity=identity,
                            category_name=row_category,
                        )
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
                        if candidates:
                            self._save_probable_duplicate(
                                upload=upload,
                                trans=trans,
                                candidates=candidates,
                                type_value=type_value,
                                row_position=row_position,
                                category_name=row_category,
                                match_calendar_date=source == 'ozon',
                                identity=identity,
                            )
                            skipped_count += 1
                        else:
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
                                source_ref=None,
                                source_ref_hash=identity.source_ref_hash,
                                source_ref_key_id=identity.key_id,
                                source_ref_version=identity.version,
                                source_identity_trusted=identity.trusted,
                                source_file_hash=upload.file_hash or None,
                                source_row_position=row_position,
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

    def _precheck_blocks_posting(
        self,
        *,
        upload: BankStatementUpload,
        source_ref: str | None,
        row_position: int,
        bank_code: str | None,
    ) -> bool:
        """Skip the network classifier for rows already known to need none."""
        if self.identity_service.same_file_posted(
            account_id=upload.account_id,
            source_file_hash=upload.file_hash,
            source_row_position=row_position,
        ):
            return True
        if not source_ref:
            return False
        identity = self.identity_service.classify_incoming(
            account_id=upload.account_id,
            bank_code=bank_code,
            source_ref=source_ref,
            trusted_reference=self.identity_service.reference_is_trusted(
                bank_code,
                source_ref,
            ),
            exclude_upload_id=upload.pk,
        )
        return identity.exact_duplicate or identity.manual

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
        bank_code: str | None,
        generation: StatementGeneration,
    ) -> None:
        """Save rows awaiting user markup; none of them is posted.

        Every parsed representation is kept: a synthetic per-bank reference
        is not trusted evidence of an exact cross-file duplicate, so a
        repeated period adds rows for the user to decide, while the unique
        file position keeps a rerun of the same upload idempotent.
        """
        with transaction.atomic():
            # Serialize overlapping uploads of one account.
            self.account_repository.get_by_ids_for_update({upload.account_id})
            locked_upload = BankStatementUpload.objects.select_for_update().get(
                pk=upload.pk,
            )
            self._assert_generation(locked_upload, generation)
            created = self._create_markup_rows(
                locked_upload,
                transactions,
                bank_code,
            )
            locked_upload.processed_transactions = len(transactions)
            locked_upload.skipped_count = len(transactions) - created
            locked_upload.progress = 100
            locked_upload.save(
                update_fields=[
                    'processed_transactions',
                    'skipped_count',
                    'progress',
                    'updated_at',
                ],
            )
        upload.processed_transactions = locked_upload.processed_transactions
        upload.skipped_count = locked_upload.skipped_count
        upload.progress = locked_upload.progress

    def _create_markup_rows(
        self,
        upload: BankStatementUpload,
        transactions: list[dict[str, Any]],
        bank_code: str | None,
    ) -> int:
        positions = {
            idx: trans.get('row_position', idx)
            for idx, trans in enumerate(transactions)
        }
        identities: dict[int, IncomingStatementIdentity] = {}
        for idx, trans in enumerate(transactions):
            if trans.get('parse_error_code'):
                continue
            identities[positions[idx]] = (
                self.identity_service.classify_incoming(
                    account_id=upload.account_id,
                    bank_code=bank_code,
                    source_ref=trans['source_ref'],
                    trusted_reference=(
                        self.identity_service.reference_is_trusted(
                            bank_code,
                            trans['source_ref'],
                        )
                    ),
                    exclude_upload_id=upload.pk,
                )
            )
        # A cancel of a debit from an earlier upload is an income to mark up.
        by_position = {
            positions[idx]: trans for idx, trans in enumerate(transactions)
        }
        cancelled = _mutual_cancel_positions(by_position)
        rows = [
            BankStatementRow(
                upload=upload,
                **self._markup_values(
                    trans,
                    identities.get(positions[idx]),
                    positions[idx],
                    cancelled,
                ),
            )
            for idx, trans in enumerate(transactions)
        ]
        # A rerun of the same upload hits the per-upload row constraint.
        BankStatementRow.objects.bulk_create(rows, ignore_conflicts=True)
        saved = list(
            BankStatementRow.objects.filter(
                upload=upload,
                source_row_position__in=positions.values(),
            ),
        )
        for row in saved:
            position = row.source_row_position
            if position is None:
                continue
            if position not in by_position:
                continue
            trans = by_position[position]
            identity = identities.get(position)
            if (
                row.decision == BankStatementRow.Decision.PARSE_ERROR
                and identity is not None
                and not trans.get('parse_error_code')
            ):
                # A parser fix makes the same physical row readable again.
                BankStatementRow.objects.filter(
                    pk=row.pk,
                    decision=BankStatementRow.Decision.PARSE_ERROR,
                ).update(
                    resume_decision='',
                    **{
                        key: value
                        for key, value in self._markup_values(
                            trans,
                            identity,
                            position,
                            cancelled,
                        ).items()
                        if key != 'source_row_position'
                    },
                )
            if identity is not None and identity.matched_transactions:
                self._add_identity_candidates(
                    row,
                    identity.matched_transactions,
                )
        return len(rows)

    @staticmethod
    def _markup_values(
        trans: dict[str, Any],
        identity: IncomingStatementIdentity | None,
        position: int,
        cancelled: set[int],
    ) -> dict[str, Any]:
        """Bank fields of one markup row; unknown values stay unknown."""
        amount = trans.get('amount')
        error_code = trans.get('parse_error_code') or ''
        return {
            'transaction_type': (
                None
                if amount is None
                else (
                    TransactionType.INCOME
                    if amount > 0
                    else TransactionType.EXPENSE
                )
            ),
            'transaction_date': trans.get('date'),
            'amount': abs(amount) if amount is not None else None,
            'description': strip_pii(str(trans.get('description') or ''))[
                : constants.TWO_HUNDRED_FIFTY
            ],
            'candidate_description': (
                identity.manual_reason[: constants.TWO_HUNDRED_FIFTY]
                if identity is not None
                else ''
            ),
            'source_ref': None,
            'source_ref_hash': (
                identity.source_ref_hash if identity is not None else None
            ),
            'source_ref_key_id': identity.key_id
            if identity is not None
            else '',
            'source_ref_version': identity.version
            if identity is not None
            else 1,
            'source_identity_trusted': (
                identity.trusted if identity is not None else False
            ),
            'source_row_position': position,
            'duplicate_of_id': (
                identity.duplicate_of_id if identity is not None else None
            ),
            'match_calendar_date': trans.get('date') is not None,
            'kind': str(trans.get('kind') or ''),
            'merchant_key': trans.get('merchant_key') or '',
            'counterparty_account': trans.get('counterparty_account') or '',
            'date_precision': (
                trans.get('date_precision')
                or BankStatementRow.DatePrecision.UNKNOWN
            ),
            'parse_error_code': error_code,
            'decision': (
                BankStatementRow.Decision.PARSE_ERROR
                if error_code
                else (
                    BankStatementRow.Decision.MUTUAL_CANCEL
                    if position in cancelled
                    else BankStatementRow.Decision.AWAITING_MARKUP
                )
            ),
        }

    def _save_manual_row(
        self,
        *,
        upload: BankStatementUpload,
        trans: dict[str, Any],
        type_value: str,
        row_position: int,
        identity: IncomingStatementIdentity,
        category_name: str,
    ) -> BankStatementRow:
        """Keep a normalized row for manual reconciliation, never posting it."""
        row = self.identity_repository.create_manual_row(
            upload=upload,
            source_row_position=row_position,
            defaults={
                'transaction_type': type_value,
                'transaction_date': trans['date'],
                'amount': abs(trans['amount']),
                'description': strip_pii(str(trans['description']))[:250],
                'candidate_description': identity.manual_reason[
                    : constants.TWO_HUNDRED_FIFTY
                ],
                'suggested_category': category_name[
                    : constants.TWO_HUNDRED_FIFTY
                ],
                'source_ref': None,
                'source_ref_hash': identity.source_ref_hash,
                'source_ref_key_id': identity.key_id,
                'source_ref_version': identity.version,
                'source_identity_trusted': identity.trusted,
                'duplicate_of_id': identity.duplicate_of_id,
                'match_calendar_date': trans.get('source') == 'ozon',
                'decision': BankStatementRow.Decision.PENDING,
            },
        )
        self._add_identity_candidates(row, identity.matched_transactions)
        return row

    def _add_identity_candidates(
        self,
        row: BankStatementRow,
        transactions: tuple[Transaction, ...],
    ) -> None:
        self.identity_repository.add_statement_candidates(
            row,
            [
                (
                    transaction,
                    transaction.description or str(transaction.category.name),
                )
                for transaction in transactions
            ],
        )

    def _save_needs_transfer_row(
        self,
        *,
        upload: BankStatementUpload,
        trans: dict[str, Any],
        row_position: int,
        identity: IncomingStatementIdentity,
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
                'candidate_description': identity.manual_reason[
                    : constants.TWO_HUNDRED_FIFTY
                ],
                'source_ref': None,
                'source_ref_hash': identity.source_ref_hash,
                'source_ref_key_id': identity.key_id,
                'source_ref_version': identity.version,
                'source_identity_trusted': identity.trusted,
                'duplicate_of_id': identity.duplicate_of_id,
                'decision': BankStatementRow.Decision.NEEDS_TRANSFER,
            },
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
        identity: IncomingStatementIdentity,
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
                'source_ref': None,
                'source_ref_hash': identity.source_ref_hash,
                'source_ref_key_id': identity.key_id,
                'source_ref_version': identity.version,
                'source_identity_trusted': identity.trusted,
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


def _mutual_cancel_positions(rows: dict[int, dict[str, Any]]) -> set[int]:
    """Pair each cancel with a debit of the same device owner and amount."""
    debits: dict[tuple[str, Decimal], list[int]] = {}
    for idx, trans in rows.items():
        amount = trans.get('amount')
        if (
            trans.get('kind') == RosDorBankRowKind.CARD
            and amount is not None
            and amount < 0
        ):
            debits.setdefault(
                (trans['description'], -amount),
                [],
            ).append(idx)
    positions: set[int] = set()
    for idx, trans in rows.items():
        if trans.get('kind') != RosDorBankRowKind.CANCEL:
            continue
        amount = trans.get('amount')
        if amount is None:
            continue
        matches = debits.get((trans['description'], amount))
        if matches:
            positions |= {matches.pop(0), idx}
    return positions
