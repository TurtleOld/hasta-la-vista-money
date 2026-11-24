"""Единый сервис импорта банковской выписки.

Инкапсулирует разбор PDF, дедупликацию (точный дубликат, вероятный дубль,
легаси-фолбэк), категоризацию и проводку финансового движения. Используется
Celery-задачей ``process_bank_statement_task``, которая остаётся единственным
прод-швом — в том числе для тестов (``process_bank_statement_task.apply(...)``)
— второй самостоятельной реализации импорта в проекте нет.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

import structlog
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.bank_constants import (
    BANK_DEFAULT,
    BANK_RAIFFEISENBANK,
    BANK_SBERBANK,
)
from hasta_la_vista_money.finance_account.models import (
    Bank,
    TransferMoneyLog,
)
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
    BankStatementDecisionAudit,
    BankStatementRow,
    BankStatementUpload,
    User,
    bank_statement_expires_at,
)
from hasta_la_vista_money.users.repositories.transfer_matching import (
    find_mirroring_transfers,
    local_row_date,
)
from hasta_la_vista_money.users.services.bank_statement import (
    BankStatementParseError,
    BankStatementParser,
    RosDorBankRowKind,
    StatementParseResult,
)
from hasta_la_vista_money.users.services.pii_stripper import strip_pii
from hasta_la_vista_money.users.services.statement_identity import (
    StatementFingerprint,
    StatementFingerprintUnavailableError,
    StatementIdentityService,
)

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile

    from hasta_la_vista_money.finance_account.models import Account
    from hasta_la_vista_money.finance_account.repositories import (
        AccountRepository,
    )
    from hasta_la_vista_money.users.protocols.services import (
        StatementCoverageServiceProtocol,
    )
    from hasta_la_vista_money.users.repositories.statement_row_repository import (  # noqa: E501
        StatementRowRepository,
    )
    from hasta_la_vista_money.users.services.category_classifier import (
        CategoryClassifier,
    )

logger = structlog.get_logger(__name__)
FALLBACK_CATEGORY = 'Без категории'
# Banks whose parsed rows may be posted only by a closed local category rule.
# A generic statement has no bank identity, so only table structure and a
# locally known category can post it.
LOCAL_CATEGORY_BANKS = frozenset({'raiffeisen', 'sberbank', 'ozon', 'generic'})
# Banks whose reference is a hint: only file hash, stable format and
# matching operation fields can prove an exact repeat.
WEAK_REFERENCE_BANKS = frozenset({'raiffeisen', 'sberbank', 'ozon', 'generic'})
# System banks that unambiguously identify one supported statement adapter.
STATEMENT_BANK_SYSTEM_IDENTITIES = {
    BANK_SBERBANK: 'sberbank',
    BANK_RAIFFEISENBANK: 'raiffeisen',
}
# Personal banks have no stable code, so a confirmed name token must name
# the same bank the adapter detected.
STATEMENT_BANK_NAME_ALIASES = {
    'raiffeisen': frozenset(
        {'raiffeisen', 'raiffaisen', 'райффайзен', 'райфайзен'},
    ),
    'sberbank': frozenset({'sber', 'сбер'}),
    'ozon': frozenset({'ozon', 'озон'}),
    'rosdorbank': frozenset({'rosdor', 'росдор'}),
}
BANK_NAME_SUFFIXES = ('банк', 'bank')


def _account_bank_name_tokens(name: str) -> set[str]:
    """Return normalized name tokens of a personal bank."""
    words = ''.join(
        char if char.isalnum() else ' ' for char in name.casefold()
    ).split()
    tokens: set[str] = set()
    for word in words:
        token = word
        for suffix in BANK_NAME_SUFFIXES:
            if token.endswith(suffix) and len(token) > len(suffix):
                token = token[: -len(suffix)]
                break
        if token and token not in BANK_NAME_SUFFIXES:
            tokens.add(token)
    return tokens


def _account_bank_identity(account_bank: Bank) -> str | None:
    """Return a reliably recognized statement-adapter identity, if any.

    A default bank, an arbitrary personal name and a name that fits several
    known banks prove no identity. Only one recognized known bank counts.
    """
    if account_bank.code == BANK_DEFAULT:
        return None
    identity = STATEMENT_BANK_SYSTEM_IDENTITIES.get(account_bank.code)
    if identity is not None:
        return identity
    tokens = _account_bank_name_tokens(account_bank.name)
    identities = {
        bank
        for bank, aliases in STATEMENT_BANK_NAME_ALIASES.items()
        if tokens & aliases
    }
    if len(identities) == 1:
        return identities.pop()
    return None


def _account_bank_matches_statement(
    account_bank: Bank,
    statement_bank: str,
) -> bool:
    """Return whether the statement bank is safe for the account bank.

    A generic/unknown detected format and an unconfirmed or ambiguous
    account bank prove no mismatch, so existing supported processing is
    kept. Only a reliably recognized different bank blocks the import.
    """
    if statement_bank not in STATEMENT_BANK_NAME_ALIASES:
        return True
    identity = _account_bank_identity(account_bank)
    return identity is None or identity == statement_bank


def _is_unparsed(trans: dict[str, Any]) -> bool:
    """Return whether a parsed entry lacks data needed for a movement."""
    return bool(
        trans.get('parse_issue')
        or trans.get('amount') is None
        or trans.get('date') is None,
    )


def _reference_strength(bank: str, trans: dict[str, Any]) -> str:
    """Return the trust level of a parsed row reference.

    A generic statement has no bank identity, so any reference seen there
    stays a weak hint even if malformed metadata claims otherwise.

    Args:
        bank: Bank/format code of the parse result.
        trans: One parsed statement row.

    Returns:
        ``'weak'`` or ``'strong'``.
    """
    if bank == 'generic':
        return 'weak'
    return str(trans.get('source_ref_strength') or 'weak')


def _effective_reference_strength(
    bank: str,
    trans: dict[str, Any],
    ambiguous_refs: set[str],
) -> str:
    """Return the proof level after accounting for repeated references.

    A reference that appears more than once in one parsed file is
    ambiguous inside that file. It stays a hint even when the adapter
    reports a strong identifier, so neither import nor manual markup may
    merge those observations automatically.

    Args:
        bank: Bank/format code of the parse result.
        trans: One parsed statement row.
        ambiguous_refs: References repeated inside the current file.

    Returns:
        ``'weak'`` or ``'strong'``.
    """
    if trans.get('source_ref') in ambiguous_refs:
        return 'weak'
    return _reference_strength(bank, trans)


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
        closing_balance_date: Дата конечного остатка, если известна.
        closing_balance_moment: Точный момент остатка, если банк его даёт.
        closing_balance_currency: Подтверждённая валюта остатка.
        closing_balance_semantics: Подтверждённая семантика остатка.
        stopped: Прогон остановлен, потому что очистка удалила данные,
            истёк срок хранения или загрузку уже ведёт другой прогон.
    """

    income_count: int
    expense_count: int
    skipped_count: int
    needs_transfer_count: int
    closing_balance: Decimal | None
    closing_balance_date: date | None = None
    closing_balance_moment: datetime | None = None
    closing_balance_currency: str | None = None
    closing_balance_semantics: str | None = None
    stopped: bool = False


@dataclass(frozen=True)
class ProbableDuplicate:
    """Movement already recorded that may mirror a statement row."""

    description: str
    movement: Transaction | TransferMoneyLog


@dataclass(frozen=True)
class ExactObservation:
    """Proof that an incoming row repeats one already recorded operation.

    ``conflict`` means the row position matches a different parser/format
    mapping, so the observation must be reassigned by the user instead of
    being merged or posted automatically.
    """

    row: BankStatementRow | None = None
    transaction: Transaction | None = None
    conflict: bool = False
    legacy: bool = False


class BankStatementImportService:
    """Разбирает PDF-выписку и проводит по ней финансовые движения."""

    def __init__(
        self,
        classifier: CategoryClassifier,
        account_repository: AccountRepository,
        statement_row_repository: StatementRowRepository,
        identity_service: StatementIdentityService,
        coverage_service: StatementCoverageServiceProtocol,
    ) -> None:
        """Инициализировать сервис зависимостями импорта.

        Args:
            classifier: Категоризатор операций.
            account_repository: Репозиторий счетов.
            statement_row_repository: Репозиторий строк выписки.
            identity_service: Сервис безопасной идентичности строк.
            coverage_service: Сервис покрытия периода выписки.
        """
        self.classifier = classifier
        self.account_repository = account_repository
        self.statement_row_repository = statement_row_repository
        self.identity_service = identity_service
        self.coverage_service = coverage_service

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

    def start_run(self, upload: BankStatementUpload) -> str:
        """Assign the run identifier before the task is published.

        A previous delivery keeps its old identifier, so it can neither
        claim the upload nor record a result or an error after this run
        starts. The row is locked while the identifier changes.

        Args:
            upload: Upload that is about to be published to the queue.

        Returns:
            The new run identifier to pass to the task.
        """
        run_id = uuid4().hex
        with transaction.atomic():
            locked = BankStatementUpload.objects.select_for_update().get(
                pk=upload.pk,
            )
            locked.celery_task_id = run_id
            locked.status = BankStatementUpload.Status.PENDING
            locked.failed_count = 0
            locked.error_message = ''
            locked.save(
                update_fields=[
                    'celery_task_id',
                    'status',
                    'failed_count',
                    'error_message',
                    'updated_at',
                ],
            )
        upload.celery_task_id = run_id
        upload.status = BankStatementUpload.Status.PENDING
        upload.failed_count = 0
        upload.error_message = ''
        return run_id

    def prepare_known_replay(
        self,
        upload: BankStatementUpload,
        pdf_file: UploadedFile,
    ) -> bool:
        """Start an explicit reconciliation run for one known file hash.

        The existing upload and its stable rows are reused. A file removed
        by retention is attached again, and only this upload's bank data
        gets a fresh retention deadline; decisions, links and the money
        history are left untouched.

        Args:
            upload: Existing upload found by the same account and hash.
            pdf_file: The explicitly uploaded file of that hash.

        Returns:
            ``True`` when the reconciliation run may be enqueued. ``False``
            when a fresh run is already in flight and must not be doubled.
        """
        stale_after = timedelta(
            minutes=constants.STATEMENT_UPLOAD_STALE_MINUTES,
        )
        with transaction.atomic():
            locked = (
                BankStatementUpload.objects.select_for_update()
                .select_related('account', 'user')
                .get(pk=upload.pk)
            )
            if (
                locked.status
                in {
                    BankStatementUpload.Status.PENDING,
                    BankStatementUpload.Status.PROCESSING,
                }
                and timezone.now() - locked.updated_at <= stale_after
            ):
                return False
            if not locked.pdf_file:
                locked.pdf_file.save(
                    pdf_file.name or 'statement.pdf',
                    pdf_file,
                    save=False,
                )
            locked.processing_mode = (
                BankStatementUpload.ProcessingMode.RECONCILIATION
            )
            locked.celery_task_id = uuid4().hex
            locked.status = BankStatementUpload.Status.PENDING
            locked.progress = 0
            locked.total_transactions = 0
            locked.processed_transactions = 0
            locked.income_count = 0
            locked.expense_count = 0
            locked.skipped_count = 0
            locked.imported_count = 0
            locked.linked_count = 0
            locked.awaiting_decision_count = 0
            locked.needs_transfer_count = 0
            locked.expired_count = 0
            locked.failed_count = 0
            locked.statement_closing_balance = None
            locked.account_balance_after = None
            locked.balance_discrepancy = None
            locked.error_message = ''
            locked.expires_at = bank_statement_expires_at(
                days=locked.user.statement_retention_days,
            )
            locked.retention_cleaned_at = None
            locked.save(
                update_fields=[
                    'pdf_file',
                    'processing_mode',
                    'celery_task_id',
                    'status',
                    'progress',
                    'total_transactions',
                    'processed_transactions',
                    'income_count',
                    'expense_count',
                    'skipped_count',
                    'imported_count',
                    'linked_count',
                    'awaiting_decision_count',
                    'needs_transfer_count',
                    'expired_count',
                    'failed_count',
                    'statement_closing_balance',
                    'account_balance_after',
                    'balance_discrepancy',
                    'error_message',
                    'expires_at',
                    'retention_cleaned_at',
                    'updated_at',
                ],
            )
        upload.refresh_from_db()
        return True

    def has_overlapping_period(self, upload: BankStatementUpload) -> bool:
        """Return whether another known upload of the same bank overlaps.

        Only explicitly parsed bank and period boundaries are compared. An
        unknown period proves nothing and never claims that the files do
        not overlap.
        """
        if (
            not upload.statement_bank
            or upload.statement_period_from is None
            or upload.statement_period_to is None
        ):
            return False
        return (
            BankStatementUpload.objects.filter(
                account_id=upload.account_id,
                statement_bank=upload.statement_bank,
                statement_period_from__isnull=False,
                statement_period_to__isnull=False,
                statement_period_from__lte=upload.statement_period_to,
                statement_period_to__gte=upload.statement_period_from,
            )
            .exclude(pk=upload.pk)
            .exists()
        )

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
        run_id = upload.celery_task_id
        with transaction.atomic():
            active = self._lock_current_run(upload.pk, run_id)
            if active is None:
                return self._stopped_result()
            upload = active
            self._verify_statement_bank(upload.account, parse_result.bank)
            if parse_result.account_number:
                with audit_operation(
                    kind=AuditOperationKind.STATEMENT_IMPORT,
                ):
                    self._match_account(
                        upload,
                        parse_result.account_number,
                        parse_result.bank,
                    )

            upload.total_transactions = len(transactions)
            upload.statement_bank = parse_result.bank
            upload.statement_period_from = parse_result.period_start
            upload.statement_period_to = parse_result.period_end
            upload.save(
                update_fields=[
                    'total_transactions',
                    'statement_bank',
                    'statement_period_from',
                    'statement_period_to',
                ],
            )
            if (
                upload.processing_mode
                != BankStatementUpload.ProcessingMode.RECONCILIATION
                and self.has_overlapping_period(upload)
            ):
                upload.processing_mode = (
                    BankStatementUpload.ProcessingMode.RECONCILIATION
                )
                upload.save(update_fields=['processing_mode'])
        reconciliation = (
            upload.processing_mode
            == BankStatementUpload.ProcessingMode.RECONCILIATION
        )

        self.coverage_service.record_statement_period(
            upload,
            parse_result.period_start,
            parse_result.period_end,
            run_id=run_id,
        )

        logger.info(
            'bank_statement_transactions_found',
            upload_id=upload.pk,
            transactions=len(transactions),
        )

        unsafe_identity = self._fingerprints_are_unsafe(upload)
        if reconciliation or parse_result.requires_markup or unsafe_identity:
            with audit_operation(kind=AuditOperationKind.STATEMENT_IMPORT):
                stopped = self._save_markup_rows(
                    upload,
                    transactions,
                    parse_result,
                    recognize_known=not unsafe_identity,
                    restore_existing=reconciliation,
                    run_id=run_id,
                )
                if stopped:
                    return self._stopped_result()
                upload.refresh_from_db()
                record_statement_import_summary(
                    user=upload.user,
                    account=upload.account,
                    created=0,
                    skipped_duplicates=upload.skipped_count,
                    period_from=parse_result.period_start,
                    period_to=parse_result.period_end,
                    mode=upload.processing_mode,
                )
            return StatementImportResult(
                income_count=0,
                expense_count=0,
                skipped_count=upload.skipped_count,
                needs_transfer_count=0,
                closing_balance=parse_result.closing_balance,
                closing_balance_date=parse_result.closing_balance_date,
                closing_balance_moment=parse_result.closing_balance_moment,
                closing_balance_currency=parse_result.closing_balance_currency,
                closing_balance_semantics=parse_result.closing_balance_semantics,
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
                stopped,
            ) = self._process_transactions(
                upload=upload,
                transactions=transactions,
                existing_categories=existing_categories,
                parse_result=parse_result,
                run_id=run_id,
            )
            if stopped:
                return self._stopped_result(
                    income_count=income_count,
                    expense_count=expense_count,
                    skipped_count=skipped_count,
                    needs_transfer_count=needs_transfer_count,
                )
            upload.refresh_from_db()

        return StatementImportResult(
            income_count=income_count,
            expense_count=expense_count,
            skipped_count=skipped_count,
            needs_transfer_count=needs_transfer_count,
            closing_balance=parse_result.closing_balance,
            closing_balance_date=parse_result.closing_balance_date,
            closing_balance_moment=parse_result.closing_balance_moment,
            closing_balance_currency=parse_result.closing_balance_currency,
            closing_balance_semantics=parse_result.closing_balance_semantics,
        )

    def _stopped_result(
        self,
        income_count: int = 0,
        expense_count: int = 0,
        skipped_count: int = 0,
        needs_transfer_count: int = 0,
    ) -> StatementImportResult:
        """Return a result without bank details after the run has stopped."""
        return StatementImportResult(
            income_count=income_count,
            expense_count=expense_count,
            skipped_count=skipped_count,
            needs_transfer_count=needs_transfer_count,
            closing_balance=None,
            stopped=True,
        )

    def _process_transactions(
        self,
        upload: BankStatementUpload,
        transactions: list[dict[str, Any]],
        existing_categories: list[str],
        parse_result: StatementParseResult | None = None,
        run_id: str | None = None,
    ) -> tuple[int, int, int, int, bool]:
        """Создать транзакции из разобранных записей выписки.

        Положительные строки кредитного счёта не становятся доходом:
        они сохраняются как непроведённые погашения (``needs_transfer``).
        Остальные строки проходят дедупликацию по техническому
        HMAC-отпечатку и проводку. Повтор строки не создаёт второе
        движение: строка блокируется внутри транзакции, затем проверяется
        доказанное повторное наблюдение.

        Args:
            upload: Запись загрузки для сохранения прогресса.
            transactions: Список разобранных операций.
            existing_categories: Актуальный список категорий пользователя.
            parse_result: Результат разбора с банком и версией формата.
            run_id: Идентификатор активного прогона; по умолчанию берётся
                из загрузки.

        Returns:
            Кортеж ``(income_count, expense_count, skipped_count,
            needs_transfer_count, stopped)``. ``stopped`` означает, что
            очистка, срок хранения или новый прогон запретили запись.
        """
        run_id = run_id or upload.celery_task_id
        stopped = False
        income_count = upload.income_count
        expense_count = upload.expense_count
        skipped_count = upload.skipped_count
        needs_transfer_count = upload.needs_transfer_count
        failed_count = upload.failed_count
        resume_from = upload.processed_transactions
        batch_size = 10
        total = len(transactions)
        period_from: date | None = None
        period_to: date | None = None
        ambiguous_refs = {
            ref
            for ref, count in Counter(
                trans.get('source_ref') for trans in transactions
            ).items()
            if ref and count > 1
        }
        bank = parse_result.bank if parse_result is not None else 'generic'
        format_version = (
            parse_result.format_version if parse_result is not None else 1
        )
        uses_local_categories = bank in LOCAL_CATEGORY_BANKS
        if ambiguous_refs:
            with transaction.atomic():
                active = self._lock_current_run(upload.pk, run_id)
                if active is None:
                    return (
                        income_count,
                        expense_count,
                        skipped_count,
                        needs_transfer_count,
                        True,
                    )
                BankStatementRow.objects.filter(
                    upload=active,
                    source_ref__in=ambiguous_refs,
                ).update(source_ref_strength='weak')

        for idx, trans in enumerate(transactions):
            if idx < resume_from:
                row_date = trans.get('date')
                if row_date is None:
                    continue
                row_day = (
                    row_date.date()
                    if isinstance(row_date, datetime)
                    else row_date
                )
                period_from = min(period_from or row_day, row_day)
                period_to = max(period_to or row_day, row_day)
                continue
            amount = trans.get('amount')
            description = str(trans.get('description') or '')
            trans_date = trans.get('date')
            unparsed = _is_unparsed(trans)
            source_ref = trans.get('source_ref')
            source_ref_strength = _effective_reference_strength(
                bank,
                trans,
                ambiguous_refs,
            )
            row_position = trans.get('row_position', idx)
            source = trans.get('source')
            abs_amount = abs(amount) if amount is not None else None
            match_calendar_date = (
                source == 'ozon'
                or bank in {'ozon', 'generic'}
                or bool(trans.get('date_only'))
            )
            is_credit_income = (
                amount is not None
                and amount > 0
                and upload.account.type_account
                in constants.CREDIT_ACCOUNT_TYPES
            )
            # The unparsed branch below never posts money; the casts keep
            # the money path typed after partial rows were separated.
            type_value = ''
            balance_change: Decimal = Decimal(0)
            if amount is not None:
                type_value = (
                    TransactionType.INCOME
                    if amount > 0
                    else TransactionType.EXPENSE
                )
                balance_change = (
                    cast('Decimal', abs_amount)
                    if amount > 0
                    else -cast('Decimal', abs_amount)
                )
            amount = cast('Decimal', amount)
            trans_date = cast('datetime', trans_date)
            abs_amount = cast('Decimal', abs_amount)

            exact = None
            if not unparsed and source_ref not in ambiguous_refs:
                exact = self._find_exact_observation(
                    upload=upload,
                    bank=bank,
                    source_ref=source_ref,
                    row_position=row_position,
                    type_value=type_value,
                    amount=abs_amount,
                    trans_date=trans_date,
                    match_calendar_date=match_calendar_date,
                    format_version=format_version,
                    source_ref_strength=source_ref_strength,
                )

            # The classifier is a network call: keep it out of the row
            # transaction so a slow model does not hold it open. A
            # Raiffeisen row is only posted by a closed local rule.
            category_name = trans.get('category_name')
            if (
                category_name is None
                and not unparsed
                and not is_credit_income
                and not uses_local_categories
                and not (exact is not None and not exact.conflict)
            ):
                category_name = self._classify_category(
                    strip_pii(str(description)),
                    type_value,
                    existing_categories,
                )

            with transaction.atomic():
                active = self._lock_current_run(upload.pk, run_id)
                if active is None:
                    stopped = True
                    break
                upload = active
                if upload.processed_transactions > idx:
                    income_count = upload.income_count
                    expense_count = upload.expense_count
                    skipped_count = upload.skipped_count
                    needs_transfer_count = upload.needs_transfer_count
                    failed_count = upload.failed_count
                    continue
                upload = self._lock_account(upload)
                exact = None
                if not unparsed and source_ref not in ambiguous_refs:
                    exact = self._find_exact_observation(
                        upload=upload,
                        bank=bank,
                        source_ref=source_ref,
                        row_position=row_position,
                        type_value=type_value,
                        amount=abs_amount,
                        trans_date=trans_date,
                        match_calendar_date=match_calendar_date,
                        format_version=format_version,
                        source_ref_strength=source_ref_strength,
                    )
                if uses_local_categories and not unparsed and exact is None:
                    existing_row = BankStatementRow.objects.filter(
                        upload=upload,
                        source_row_position=row_position,
                        source_format_version=format_version,
                    ).first()
                    if (
                        existing_row is not None
                        and existing_row.transaction_id is not None
                        and self._row_matches(
                            existing_row,
                            type_value=type_value,
                            amount=abs_amount,
                            trans_date=trans_date,
                            match_calendar_date=match_calendar_date,
                        )
                    ):
                        exact = ExactObservation(row=existing_row)
                if unparsed:
                    self._save_unparsed_row(
                        upload=upload,
                        trans=trans,
                        row_position=row_position,
                        bank=bank,
                        format_version=format_version,
                        source_ref_strength=source_ref_strength,
                    )
                    failed_count += 1
                elif is_credit_income:
                    self._save_needs_transfer_row(
                        upload=upload,
                        trans=trans,
                        row_position=row_position,
                        bank=bank,
                        format_version=format_version,
                        source_ref_strength=source_ref_strength,
                    )
                    needs_transfer_count += 1
                elif exact is not None and exact.conflict:
                    self._save_manual_row(
                        upload=upload,
                        trans=trans,
                        row_position=row_position,
                        type_value=type_value,
                        bank=bank,
                        format_version=format_version,
                        source_ref_strength=source_ref_strength,
                    )
                elif exact is not None:
                    saved = self._save_duplicate_row(
                        upload=upload,
                        trans=trans,
                        row_position=row_position,
                        type_value=type_value,
                        observation=exact,
                        bank=bank,
                        format_version=format_version,
                        source_ref_strength=source_ref_strength,
                    )
                    if saved.decision == BankStatementRow.Decision.DUPLICATE:
                        skipped_count += 1
                else:
                    row_category = str(category_name or FALLBACK_CATEGORY)
                    if uses_local_categories and (
                        category_name is None
                        or source_ref in ambiguous_refs
                        or self._has_unresolved_observation(
                            upload=upload,
                            bank=bank,
                            source_ref=source_ref,
                            type_value=type_value,
                            amount=abs_amount,
                            trans_date=trans_date,
                        )
                    ):
                        self._save_observation_row(
                            upload=upload,
                            trans=trans,
                            row_position=row_position,
                            type_value=type_value,
                            fingerprint=self._fingerprint(
                                upload=upload,
                                bank=bank,
                                source_ref=source_ref,
                            ),
                            format_version=format_version,
                            decision=BankStatementRow.Decision.AWAITING_MARKUP,
                            suggested_category=(
                                row_category if category_name else ''
                            ),
                            source_ref_strength=source_ref_strength,
                        )
                    else:
                        candidates = self._rank_probable_candidates(
                            account=upload.account,
                            user=upload.user,
                            type_value=type_value,
                            abs_amount=abs_amount,
                            trans_date=trans_date,
                            match_calendar_date=match_calendar_date,
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
                                match_calendar_date=match_calendar_date,
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
                            fingerprint = self._fingerprint(
                                upload=upload,
                                bank=bank,
                                source_ref=source_ref,
                            )
                            created = Transaction.objects.create(
                                user=upload.user,
                                account=upload.account,
                                category=category,
                                type=type_value,
                                amount=abs_amount,
                                date=trans_date,
                                description=strip_pii(str(description))[:250],
                                source_ref=source_ref or None,
                                source_file_hash=(
                                    upload.file_hash
                                    if (
                                        not source_ref
                                        or bank in WEAK_REFERENCE_BANKS
                                    )
                                    else None
                                ),
                                source_row_position=(
                                    row_position
                                    if (
                                        not source_ref
                                        or bank in WEAK_REFERENCE_BANKS
                                    )
                                    else None
                                ),
                                source_format_version=format_version,
                                source_fingerprint=(
                                    fingerprint.digest if fingerprint else ''
                                ),
                                source_fingerprint_key_version=(
                                    fingerprint.key_version
                                    if fingerprint
                                    else ''
                                ),
                                source_fingerprint_format_version=(
                                    fingerprint.format_version
                                    if fingerprint
                                    else 0
                                ),
                            )
                            if uses_local_categories:
                                self._save_autopost_row(
                                    upload=upload,
                                    trans=trans,
                                    row_position=row_position,
                                    type_value=type_value,
                                    fingerprint=fingerprint,
                                    format_version=format_version,
                                    transaction=created,
                                    suggested_category=row_category,
                                    source_ref_strength=source_ref_strength,
                                )
                            # Bank is source of truth: no funds check.
                            upload.account = (
                                BalanceService().apply_balance_delta(
                                    upload.account,
                                    balance_change,
                                    check_funds=False,
                                )
                            )
                            if type_value == TransactionType.INCOME:
                                income_count += 1
                            else:
                                expense_count += 1
                            row_date = trans_date.date()
                            if period_from is None or row_date < period_from:
                                period_from = row_date
                            if period_to is None or row_date > period_to:
                                period_to = row_date

                upload.processed_transactions = idx + 1
                upload.income_count = income_count
                upload.expense_count = expense_count
                upload.skipped_count = skipped_count
                upload.needs_transfer_count = needs_transfer_count
                upload.failed_count = failed_count
                upload.progress = int((idx + 1) / total * 100)
                upload.save(
                    update_fields=[
                        'processed_transactions',
                        'income_count',
                        'expense_count',
                        'skipped_count',
                        'needs_transfer_count',
                        'failed_count',
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

        if not stopped:
            record_statement_import_summary(
                user=upload.user,
                account=upload.account,
                created=income_count + expense_count,
                skipped_duplicates=skipped_count,
                period_from=period_from,
                period_to=period_to,
                mode=upload.processing_mode,
            )
        return (
            income_count,
            expense_count,
            skipped_count,
            needs_transfer_count,
            stopped,
        )

    def _lock_current_run(
        self,
        upload_id: int,
        run_id: str,
    ) -> BankStatementUpload | None:
        """Lock the upload and keep it only while this run may write.

        Cleanup takes the same lock, clears the run id and marks the data
        cleaned. A resumed worker that re-reads the row after that must
        stop instead of restoring bank details or posting newer rows.
        """
        upload = self._lock_upload(upload_id)
        if (
            upload.retention_cleaned_at is not None
            or upload.expires_at <= timezone.now()
            or upload.celery_task_id != run_id
        ):
            return None
        return upload

    def _lock_upload(self, upload_id: int) -> BankStatementUpload:
        """Lock the upload row: Celery retries and manual actions serialize."""
        return (
            BankStatementUpload.objects.select_for_update()
            .select_related('account', 'user')
            .get(pk=upload_id)
        )

    def _lock_account(
        self,
        upload: BankStatementUpload,
    ) -> BankStatementUpload:
        """Lock the account after the upload, keeping one lock order."""
        upload.account = self.account_repository.get_by_ids_for_update(
            {upload.account_id},
        )[upload.account_id]
        return upload

    def _fingerprints_are_unsafe(self, upload: BankStatementUpload) -> bool:
        """Return whether a negative conclusion cannot be proven safely."""
        if not self.identity_service.is_configured:
            return True
        stored_keys = (
            self.statement_row_repository.stored_fingerprint_key_versions(
                upload.account_id,
            )
        )
        stored_formats = (
            self.statement_row_repository.stored_fingerprint_format_versions(
                upload.account_id,
            )
        )
        return bool(
            self.identity_service.missing_keys(stored_keys)
            or self.identity_service.incompatible_format_versions(
                stored_formats,
            ),
        )

    def _fingerprint(
        self,
        *,
        upload: BankStatementUpload,
        bank: str,
        source_ref: str | None,
    ) -> StatementFingerprint | None:
        """Return the active fingerprint, or None when keys are unavailable.

        A generic statement has no bank identity, so it never gets an HMAC
        fingerprint even if malformed metadata carries a reference.
        """
        if bank == 'generic':
            return None
        try:
            return self.identity_service.fingerprint(
                bank=bank,
                account_id=upload.account_id,
                source_ref=source_ref,
            )
        except StatementFingerprintUnavailableError:
            return None

    def _find_exact_observation(
        self,
        *,
        upload: BankStatementUpload,
        bank: str,
        source_ref: str | None,
        row_position: int,
        type_value: str,
        amount: Decimal,
        trans_date: datetime,
        match_calendar_date: bool,
        format_version: int,
        source_ref_strength: str = 'weak',
    ) -> ExactObservation | None:
        """Return one proven repeat, a drift conflict, or no proof.

        A strong bank identifier must also match direction, amount and
        bank date. A weak identifier never proves a repeat by itself, but
        the same file hash, parser version and row position can. An
        unknown key or a missing fingerprint means no proof, never a
        negative conclusion.
        """
        if source_ref and source_ref_strength == 'strong':
            return self._exact_by_reference(
                upload=upload,
                bank=bank,
                source_ref=source_ref,
                type_value=type_value,
                amount=amount,
                trans_date=trans_date,
                match_calendar_date=match_calendar_date,
            )
        if source_ref and bank not in WEAK_REFERENCE_BANKS:
            return None
        if bank in WEAK_REFERENCE_BANKS and not upload.file_hash:
            return None
        return self._exact_by_position(
            upload=upload,
            row_position=row_position,
            format_version=format_version,
            type_value=type_value,
            amount=amount,
            trans_date=trans_date,
            match_calendar_date=match_calendar_date,
        )

    def _exact_by_reference(
        self,
        *,
        upload: BankStatementUpload,
        bank: str,
        source_ref: str,
        type_value: str,
        amount: Decimal,
        trans_date: datetime,
        match_calendar_date: bool,
    ) -> ExactObservation | None:
        """Return the single resolved observation with this fingerprint."""
        try:
            identities = self.identity_service.recognition(
                bank=bank,
                account_id=upload.account_id,
                source_ref=source_ref,
            )
        except StatementFingerprintUnavailableError:
            return None
        digests = [identity.digest for identity in identities]
        if not digests:
            return None
        rows = list(
            BankStatementRow.objects.filter(
                upload__account=upload.account,
                source_fingerprint__in=digests,
            )
            .exclude(
                decision__in={
                    BankStatementRow.Decision.PENDING,
                    BankStatementRow.Decision.AWAITING_MARKUP,
                    BankStatementRow.Decision.NEEDS_TRANSFER,
                    BankStatementRow.Decision.EXPIRED,
                    BankStatementRow.Decision.DUPLICATE,
                    BankStatementRow.Decision.MUTUAL_CANCEL,
                },
            )
            .exclude(
                decision=BankStatementRow.Decision.SKIPPED,
                exclusion_code='',
            )
            .order_by('pk'),
        )
        matching_rows = [
            row
            for row in rows
            if self._row_matches(
                row,
                type_value=type_value,
                amount=amount,
                trans_date=trans_date,
                match_calendar_date=match_calendar_date,
            )
        ]
        if len(matching_rows) > 1:
            return None
        if matching_rows:
            return ExactObservation(row=matching_rows[0])
        matching_transactions = [
            transaction
            for transaction in Transaction.objects.filter(
                account=upload.account,
                source_fingerprint__in=digests,
            ).order_by('pk')
            if self._transaction_matches(
                transaction,
                type_value=type_value,
                amount=amount,
                trans_date=trans_date,
                match_calendar_date=match_calendar_date,
            )
        ]
        if len(matching_transactions) == 1:
            return ExactObservation(transaction=matching_transactions[0])
        return self._legacy_exact(
            upload=upload,
            source_ref=source_ref,
            type_value=type_value,
            amount=amount,
            trans_date=trans_date,
            match_calendar_date=match_calendar_date,
        )

    def _legacy_exact(
        self,
        *,
        upload: BankStatementUpload,
        source_ref: str,
        type_value: str,
        amount: Decimal,
        trans_date: datetime,
        match_calendar_date: bool,
    ) -> ExactObservation | None:
        """Match a pre-fingerprint row, then backfill its fingerprint.

        Records created by the previous release kept the raw reference but
        no HMAC. Without this bridge a first re-import would ask the user
        again and could double the money. The raw reference alone is still
        not proof: the direction, amount and bank date must match too.
        """
        rows = [
            row
            for row in BankStatementRow.objects.filter(
                upload__account=upload.account,
                source_ref=source_ref,
                source_fingerprint='',
            )
            .exclude(
                decision__in={
                    BankStatementRow.Decision.PENDING,
                    BankStatementRow.Decision.AWAITING_MARKUP,
                    BankStatementRow.Decision.NEEDS_TRANSFER,
                    BankStatementRow.Decision.EXPIRED,
                    BankStatementRow.Decision.DUPLICATE,
                    BankStatementRow.Decision.MUTUAL_CANCEL,
                },
            )
            .exclude(
                decision=BankStatementRow.Decision.SKIPPED,
                exclusion_code='',
            )
            .order_by('pk')
            if self._row_matches(
                row,
                type_value=type_value,
                amount=amount,
                trans_date=trans_date,
                match_calendar_date=match_calendar_date,
            )
        ]
        if len(rows) == 1:
            return ExactObservation(row=rows[0], legacy=True)
        if rows:
            return None
        transactions = [
            transaction
            for transaction in Transaction.objects.filter(
                account=upload.account,
                source_ref=source_ref,
                source_fingerprint='',
            ).order_by('pk')
            if self._transaction_matches(
                transaction,
                type_value=type_value,
                amount=amount,
                trans_date=trans_date,
                match_calendar_date=match_calendar_date,
            )
        ]
        if len(transactions) == 1:
            return ExactObservation(transaction=transactions[0], legacy=True)
        return None

    def _exact_by_position(
        self,
        *,
        upload: BankStatementUpload,
        row_position: int,
        format_version: int,
        type_value: str,
        amount: Decimal,
        trans_date: datetime,
        match_calendar_date: bool,
    ) -> ExactObservation | None:
        """Return a position match or a parser/format drift conflict."""
        existing = Transaction.objects.filter(
            account=upload.account,
            source_file_hash=upload.file_hash,
            source_row_position=row_position,
        )
        if not existing.exists():
            return None
        matching = existing.filter(source_format_version=format_version)
        for movement in matching:
            if self._transaction_matches(
                movement,
                type_value=type_value,
                amount=amount,
                trans_date=trans_date,
                match_calendar_date=match_calendar_date,
            ):
                return ExactObservation(transaction=movement)
        return ExactObservation(conflict=True)

    @staticmethod
    def _row_matches(
        row: BankStatementRow,
        *,
        type_value: str,
        amount: Decimal,
        trans_date: datetime,
        match_calendar_date: bool,
    ) -> bool:
        if (
            row.transaction_type != type_value
            or row.amount != amount
            or row.transaction_date is None
        ):
            return False
        if match_calendar_date:
            return (
                timezone.localtime(row.transaction_date).date()
                == timezone.localtime(trans_date).date()
            )
        return row.transaction_date == trans_date

    @staticmethod
    def _transaction_matches(
        transaction: Transaction,
        *,
        type_value: str,
        amount: Decimal,
        trans_date: datetime,
        match_calendar_date: bool,
    ) -> bool:
        if transaction.type != type_value or transaction.amount != amount:
            return False
        if match_calendar_date:
            return (
                timezone.localtime(transaction.date).date()
                == timezone.localtime(trans_date).date()
            )
        return transaction.date == trans_date

    def _save_duplicate_row(
        self,
        *,
        upload: BankStatementUpload,
        trans: dict[str, Any],
        row_position: int,
        type_value: str,
        observation: ExactObservation,
        bank: str,
        format_version: int,
        source_ref_strength: str | None = None,
    ) -> BankStatementRow:
        """Record an exact repeat without touching money."""
        fingerprint = self._fingerprint(
            upload=upload,
            bank=bank,
            source_ref=trans.get('source_ref'),
        )
        if source_ref_strength is None:
            source_ref_strength = _reference_strength(bank, trans)
        if observation.legacy:
            self._backfill_legacy_fingerprint(
                row=observation.row,
                transaction=observation.transaction,
                fingerprint=fingerprint,
            )
        if observation.row is None and observation.transaction is not None:
            canonical = (
                BankStatementRow.objects.filter(
                    transaction=observation.transaction,
                )
                .exclude(
                    decision__in={
                        BankStatementRow.Decision.PENDING,
                        BankStatementRow.Decision.AWAITING_MARKUP,
                        BankStatementRow.Decision.NEEDS_TRANSFER,
                        BankStatementRow.Decision.EXPIRED,
                        BankStatementRow.Decision.MUTUAL_CANCEL,
                    },
                )
                .order_by('pk')
                .first()
            )
            if canonical is not None:
                return self._save_observation_row(
                    upload=upload,
                    trans=trans,
                    row_position=row_position,
                    type_value=type_value,
                    fingerprint=fingerprint,
                    format_version=format_version,
                    decision=BankStatementRow.Decision.DUPLICATE,
                    canonical_row=canonical,
                    source_ref_strength=source_ref_strength,
                )
            # No canonical row exists yet: link the observation to the
            # proven movement instead of claiming a duplicate of nothing.
            return self._save_observation_row(
                upload=upload,
                trans=trans,
                row_position=row_position,
                type_value=type_value,
                fingerprint=fingerprint,
                format_version=format_version,
                decision=BankStatementRow.Decision.LINKED,
                transaction=observation.transaction,
                source_ref_strength=source_ref_strength,
            )
        return self._save_observation_row(
            upload=upload,
            trans=trans,
            row_position=row_position,
            type_value=type_value,
            fingerprint=fingerprint,
            format_version=format_version,
            decision=BankStatementRow.Decision.DUPLICATE,
            canonical_row=observation.row,
            source_ref_strength=source_ref_strength,
        )

    @staticmethod
    def _backfill_legacy_fingerprint(
        *,
        row: BankStatementRow | None,
        transaction: Transaction | None,
        fingerprint: StatementFingerprint | None,
    ) -> None:
        """Write the active fingerprint onto one pre-fingerprint record."""
        if fingerprint is None:
            return
        fields = {
            'source_fingerprint': fingerprint.digest,
            'source_fingerprint_key_version': fingerprint.key_version,
            'source_fingerprint_format_version': fingerprint.format_version,
        }
        if row is not None and not row.source_fingerprint:
            BankStatementRow.objects.filter(pk=row.pk).update(**fields)
        if transaction is not None and not transaction.source_fingerprint:
            Transaction.objects.filter(pk=transaction.pk).update(**fields)

    def _save_manual_row(
        self,
        *,
        upload: BankStatementUpload,
        trans: dict[str, Any],
        row_position: int,
        type_value: str,
        bank: str,
        format_version: int,
        source_ref_strength: str | None = None,
    ) -> BankStatementRow:
        """Store a row whose parser/format mapping drifted for reassignment."""
        return self._save_observation_row(
            upload=upload,
            trans=trans,
            row_position=row_position,
            type_value=type_value,
            fingerprint=self._fingerprint(
                upload=upload,
                bank=bank,
                source_ref=trans.get('source_ref'),
            ),
            format_version=format_version,
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
            source_ref_strength=(
                source_ref_strength
                if source_ref_strength is not None
                else _reference_strength(bank, trans)
            ),
        )

    @staticmethod
    def _save_observation_row(
        *,
        upload: BankStatementUpload,
        trans: dict[str, Any],
        row_position: int,
        type_value: str,
        fingerprint: StatementFingerprint | None,
        format_version: int,
        decision: str,
        canonical_row: BankStatementRow | None = None,
        transaction: Transaction | None = None,
        suggested_category: str = '',
        source_ref_strength: str = 'weak',
    ) -> BankStatementRow:
        """Create one row that records an observation without money."""
        row, created = BankStatementRow.objects.get_or_create(
            upload=upload,
            source_row_position=row_position,
            defaults={
                'transaction_type': type_value,
                'transaction_date': trans['date'],
                'amount': (
                    abs(trans['amount'])
                    if trans.get('amount') is not None
                    else None
                ),
                'description': strip_pii(str(trans['description']))[
                    : constants.TWO_HUNDRED_FIFTY
                ],
                'suggested_category': suggested_category[
                    : constants.TWO_HUNDRED_FIFTY
                ],
                'source_ref': trans.get('source_ref') or None,
                'source_ref_strength': source_ref_strength,
                'canonical_row': canonical_row,
                'transaction': transaction,
                'match_calendar_date': bool(trans.get('date_only')),
                'source_format_version': format_version,
                'source_fingerprint': (
                    fingerprint.digest if fingerprint else ''
                ),
                'source_fingerprint_key_version': (
                    fingerprint.key_version if fingerprint else ''
                ),
                'source_fingerprint_format_version': (
                    fingerprint.format_version if fingerprint else 0
                ),
                'decision': decision,
            },
        )
        if not created and row.source_ref_strength != source_ref_strength:
            BankStatementRow.objects.filter(pk=row.pk).update(
                source_ref_strength=source_ref_strength,
            )
            row.source_ref_strength = source_ref_strength
        return row

    def _save_unparsed_row(
        self,
        *,
        upload: BankStatementUpload,
        trans: dict[str, Any],
        row_position: int,
        bank: str,
        format_version: int,
        source_ref_strength: str | None = None,
    ) -> BankStatementRow:
        """Record a row fragment that cannot be posted or fully parsed."""
        amount = trans.get('amount')
        type_value = ''
        if amount is not None:
            type_value = (
                TransactionType.INCOME
                if amount > 0
                else TransactionType.EXPENSE
            )
        return self._save_observation_row(
            upload=upload,
            trans={**trans, 'description': trans.get('description') or ''},
            row_position=row_position,
            type_value=type_value,
            fingerprint=self._fingerprint(
                upload=upload,
                bank=bank,
                source_ref=trans.get('source_ref'),
            ),
            format_version=format_version,
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
            source_ref_strength=(
                source_ref_strength
                if source_ref_strength is not None
                else _reference_strength(bank, trans)
            ),
        )

    def _save_autopost_row(
        self,
        *,
        upload: BankStatementUpload,
        trans: dict[str, Any],
        row_position: int,
        type_value: str,
        fingerprint: StatementFingerprint | None,
        format_version: int,
        transaction: Transaction,
        suggested_category: str,
        source_ref_strength: str = 'weak',
    ) -> BankStatementRow:
        """Link an auto-posted movement, including an existing open row."""
        row = self._save_observation_row(
            upload=upload,
            trans=trans,
            row_position=row_position,
            type_value=type_value,
            fingerprint=fingerprint,
            format_version=format_version,
            decision=BankStatementRow.Decision.NEW,
            transaction=transaction,
            suggested_category=suggested_category,
            source_ref_strength=source_ref_strength,
        )
        if (
            row.transaction_id == transaction.pk
            and row.decision == BankStatementRow.Decision.NEW
        ):
            return row
        BankStatementRow.objects.filter(
            pk=row.pk,
            transaction__isnull=True,
        ).update(
            transaction=transaction,
            decision=BankStatementRow.Decision.NEW,
            transaction_type=type_value,
            transaction_date=trans['date'],
            amount=abs(trans['amount']),
            description=strip_pii(str(trans['description']))[
                : constants.TWO_HUNDRED_FIFTY
            ],
            source_ref=trans.get('source_ref') or None,
            source_ref_strength=source_ref_strength,
            source_format_version=format_version,
            source_fingerprint=(fingerprint.digest if fingerprint else ''),
            source_fingerprint_key_version=(
                fingerprint.key_version if fingerprint else ''
            ),
            source_fingerprint_format_version=(
                fingerprint.format_version if fingerprint else 0
            ),
            suggested_category=suggested_category[
                : constants.TWO_HUNDRED_FIFTY
            ],
        )
        row.refresh_from_db()
        return row

    def _verify_statement_bank(
        self,
        account: Account,
        statement_bank: str,
    ) -> None:
        """Reject a statement whose detected bank is another confirmed bank.

        Raises:
            BankStatementParseError: The account bank is confirmed and does
                not match the detected statement bank.
        """
        if _account_bank_matches_statement(account.bank, statement_bank):
            return
        raise BankStatementParseError(
            _(
                'Банк выписки не совпадает с банком выбранного счёта.',
            ),
        )

    def _match_account(
        self,
        upload: BankStatementUpload,
        account_number: str,
        statement_bank: str,
    ) -> None:
        """Pick the account by the statement number or record the number.

        Raises:
            BankStatementParseError: The selected account has another
                number, the number cannot be recorded, or the found account
                belongs to another confirmed bank.
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
        self._verify_statement_bank(matched, statement_bank)
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
        parse_result: StatementParseResult,
        *,
        recognize_known: bool,
        restore_existing: bool = False,
        run_id: str | None = None,
    ) -> bool:
        """Save rows awaiting user markup; none of them is posted.

        When fingerprint keys are usable, rows already proven on the
        account become exact duplicate observations. Without usable keys
        every row is saved for manual resolution: a missing key never
        turns into "the operation does not exist" or auto-posting. A weak
        or ambiguous bank reference cannot prove a cross-file repeat, so
        it never suppresses a row or becomes an exact duplicate, even when
        another upload holds the same unresolved observation. The repeated
        observation stays unresolved until a proven match or a user
        decision.

        In reconciliation mode an existing row of this same upload is
        restored from the re-uploaded file in place, keeping its decision,
        movement, transfer and candidate links. A new row during a replay
        is still only saved for resolution, never posted.

        Returns:
            ``True`` when the run had to stop because cleanup, the
            retention deadline or another run already owns the upload.
        """
        bank = parse_result.bank
        format_version = parse_result.format_version
        run_id = run_id or upload.celery_task_id
        ambiguous_refs = {
            ref
            for ref, count in Counter(
                trans.get('source_ref') for trans in transactions
            ).items()
            if ref and count > 1
        }
        with transaction.atomic():
            active = self._lock_current_run(upload.pk, run_id)
            if active is None:
                return True
            upload = self._lock_account(active)
            if ambiguous_refs:
                BankStatementRow.objects.filter(
                    upload=upload,
                    source_ref__in=ambiguous_refs,
                ).update(source_ref_strength='weak')
            new_rows: dict[int, dict[str, Any]] = {}
            duplicates: list[tuple[dict[str, Any], int, ExactObservation]] = []
            repeated_positions: set[int] = set()
            replay = restore_existing and upload.statement_rows.exists()
            for idx, trans in enumerate(transactions):
                source_position = trans.get('row_position')
                position = (
                    idx if source_position is None else int(source_position)
                )
                source_ref_strength = _effective_reference_strength(
                    bank,
                    trans,
                    ambiguous_refs,
                )
                fingerprint = self._fingerprint(
                    upload=upload,
                    bank=bank,
                    source_ref=trans.get('source_ref'),
                )
                if restore_existing and self._restore_existing_row(
                    upload=upload,
                    trans=trans,
                    row_position=position,
                    bank=bank,
                    fingerprint=fingerprint,
                    format_version=format_version,
                    source_ref_strength=source_ref_strength,
                ):
                    continue
                if _is_unparsed(trans):
                    new_rows[position] = trans
                    continue
                if (
                    recognize_known
                    and trans.get('source_ref') not in ambiguous_refs
                ):
                    exact = self._find_exact_observation(
                        upload=upload,
                        bank=bank,
                        source_ref=trans.get('source_ref'),
                        row_position=position,
                        type_value=(
                            TransactionType.INCOME
                            if trans['amount'] > 0
                            else TransactionType.EXPENSE
                        ),
                        amount=abs(trans['amount']),
                        trans_date=trans['date'],
                        match_calendar_date=(
                            bool(trans.get('date_only'))
                            if bank == 'raiffeisen'
                            else True
                        ),
                        format_version=format_version,
                        source_ref_strength=source_ref_strength,
                    )
                    if exact is not None and not exact.conflict:
                        duplicates.append((trans, position, exact))
                        continue
                    if self._has_unresolved_observation(
                        upload=upload,
                        bank=bank,
                        source_ref=trans.get('source_ref'),
                        type_value=(
                            TransactionType.INCOME
                            if trans['amount'] > 0
                            else TransactionType.EXPENSE
                        ),
                        amount=abs(trans['amount']),
                        trans_date=trans['date'],
                    ):
                        # Keep the separate unresolved trace for every
                        # bank, but never auto-pair a repeat observation
                        # with a new cancel from another upload.
                        repeated_positions.add(position)
                new_rows[position] = trans
            # A cancel of a debit from an earlier upload is an income to
            # mark up.
            cancelled = _mutual_cancel_positions(
                new_rows,
                excluded_positions=repeated_positions,
            )
            rows = []
            for position, trans in new_rows.items():
                amount = trans.get('amount')
                fingerprint = self._fingerprint(
                    upload=upload,
                    bank=bank,
                    source_ref=trans.get('source_ref'),
                )
                rows.append(
                    BankStatementRow(
                        upload=upload,
                        transaction_type=(
                            None
                            if amount is None
                            else (
                                TransactionType.INCOME
                                if amount > 0
                                else TransactionType.EXPENSE
                            )
                        ),
                        transaction_date=trans.get('date'),
                        amount=abs(amount) if amount is not None else None,
                        description=strip_pii(str(trans['description']))[
                            : constants.TWO_HUNDRED_FIFTY
                        ],
                        suggested_category=str(
                            trans.get('category_name') or '',
                        )[: constants.TWO_HUNDRED_FIFTY],
                        source_ref=trans.get('source_ref'),
                        source_ref_strength=_effective_reference_strength(
                            bank,
                            trans,
                            ambiguous_refs,
                        ),
                        source_row_position=position,
                        source_format_version=format_version,
                        source_fingerprint=(
                            fingerprint.digest if fingerprint else ''
                        ),
                        source_fingerprint_key_version=(
                            fingerprint.key_version if fingerprint else ''
                        ),
                        source_fingerprint_format_version=(
                            fingerprint.format_version if fingerprint else 0
                        ),
                        match_calendar_date=(
                            bool(trans.get('date_only'))
                            if bank == 'raiffeisen'
                            else True
                        ),
                        kind=str(trans.get('kind', '')),
                        merchant_key=trans.get('merchant_key') or '',
                        counterparty_account=(
                            trans.get('counterparty_account') or ''
                        ),
                        decision=(
                            BankStatementRow.Decision.MUTUAL_CANCEL
                            if position in cancelled
                            else BankStatementRow.Decision.AWAITING_MARKUP
                        ),
                    ),
                )
            # A rerun of the same upload hits the per-upload row
            # constraint.
            BankStatementRow.objects.bulk_create(rows, ignore_conflicts=True)
            for trans, position, exact in duplicates:
                self._save_duplicate_row(
                    upload=upload,
                    trans=trans,
                    row_position=position,
                    type_value=(
                        TransactionType.INCOME
                        if trans['amount'] > 0
                        else TransactionType.EXPENSE
                    ),
                    observation=exact,
                    bank=bank,
                    format_version=format_version,
                    source_ref_strength=_effective_reference_strength(
                        bank,
                        trans,
                        ambiguous_refs,
                    ),
                )
            upload.processed_transactions = len(transactions)
            upload.skipped_count = (
                len(duplicates) if replay else len(transactions) - len(rows)
            )
            upload.failed_count = sum(
                1 for trans in transactions if _is_unparsed(trans)
            )
            upload.progress = 100
            upload.save(
                update_fields=[
                    'processed_transactions',
                    'skipped_count',
                    'failed_count',
                    'progress',
                    'updated_at',
                ],
            )
        return False

    def _restore_existing_row(
        self,
        *,
        upload: BankStatementUpload,
        trans: dict[str, Any],
        row_position: int,
        bank: str,
        fingerprint: StatementFingerprint | None,
        format_version: int,
        source_ref_strength: str,
    ) -> BankStatementRow | None:
        """Restore one re-uploaded row in place, keeping its decisions.

        The row is matched by its bank fingerprint when one exists, or by
        the same stable position only within the same parser/format
        version. A stale position from another mapping is detached so the
        row can be reassigned instead of silently merged. Only blank bank
        fields are filled: movement, transfer, candidate and canonical
        links stay exactly as they were.

        A row expired by retention has no user decision behind it, so
        restoring its bank data reopens it for manual resolution: a parsed
        row becomes pending, an unparsed fragment awaits markup. The
        transition is written to the decision history without posting
        money. Every real decision is kept as is.
        """
        rows = BankStatementRow.objects.select_for_update().filter(
            upload=upload,
        )
        row = None
        if fingerprint is not None:
            candidate = rows.filter(
                source_fingerprint=fingerprint.digest,
            ).first()
            if candidate is not None:
                stable_format = (
                    candidate.source_format_version == format_version
                )
                unique_reference = (
                    rows.filter(
                        source_fingerprint=fingerprint.digest,
                    ).count()
                    == 1
                )
                if source_ref_strength == 'strong' or (
                    stable_format and unique_reference
                ):
                    row = candidate
        if row is None:
            row = rows.filter(
                source_row_position=row_position,
                source_format_version=format_version,
            ).first()
        if row is None:
            # An unstamped position is missing evidence, not proven parser
            # drift: the same upload replay may restore it in place and
            # stamp the current format. The bank reference must still match,
            # so a dropped format never merges a different operation. A
            # recorded different format stays a conflict for manual
            # reassignment.
            legacy_position = rows.filter(
                source_row_position=row_position,
                source_format_version=0,
                source_fingerprint='',
            ).first()
            if legacy_position is not None and (
                (legacy_position.source_ref or '')
                == (trans.get('source_ref') or '')
            ):
                row = legacy_position
        if row is None:
            stale = rows.filter(source_row_position=row_position).first()
            if stale is not None:
                BankStatementRow.objects.filter(pk=stale.pk).update(
                    source_row_position=None,
                )
            return None
        if row.amount is not None and row.transaction_date is not None:
            if row.source_ref_strength != source_ref_strength:
                BankStatementRow.objects.filter(pk=row.pk).update(
                    source_ref_strength=source_ref_strength,
                )
                row.source_ref_strength = source_ref_strength
            return row
        amount = trans.get('amount')
        trans_date = trans.get('date')
        payload: dict[str, Any] = {
            'description': strip_pii(str(trans.get('description') or ''))[
                : constants.TWO_HUNDRED_FIFTY
            ],
            'source_ref': trans.get('source_ref') or None,
            'source_ref_strength': source_ref_strength,
            'source_format_version': format_version,
            'match_calendar_date': (
                bool(trans.get('date_only')) if bank == 'raiffeisen' else True
            ),
            'kind': str(trans.get('kind', '')),
            'merchant_key': trans.get('merchant_key') or '',
            'counterparty_account': trans.get('counterparty_account') or '',
        }
        if amount is not None:
            payload['amount'] = abs(amount)
            payload['transaction_type'] = (
                BankStatementRow.TransactionType.INCOME
                if amount > 0
                else BankStatementRow.TransactionType.EXPENSE
            )
        if trans_date is not None:
            payload['transaction_date'] = trans_date
        if (
            row.source_row_position is None
            and not rows.exclude(
                pk=row.pk,
            )
            .filter(source_row_position=row_position)
            .exists()
        ):
            payload['source_row_position'] = row_position
        if fingerprint is not None:
            payload.update(
                source_fingerprint=fingerprint.digest,
                source_fingerprint_key_version=fingerprint.key_version,
                source_fingerprint_format_version=(fingerprint.format_version),
            )
        reopen = row.decision == BankStatementRow.Decision.EXPIRED
        if reopen:
            payload['decision'] = (
                BankStatementRow.Decision.AWAITING_MARKUP
                if _is_unparsed(trans)
                else BankStatementRow.Decision.PENDING
            )
            payload['decided_at'] = None
        BankStatementRow.objects.filter(pk=row.pk).update(**payload)
        row.refresh_from_db()
        if reopen:
            BankStatementDecisionAudit.objects.create(
                row=row,
                decision=row.decision,
                previous_decision=BankStatementRow.Decision.EXPIRED,
            )
        return row

    def _has_unresolved_observation(
        self,
        *,
        upload: BankStatementUpload,
        bank: str,
        source_ref: str | None,
        type_value: str,
        amount: Decimal,
        trans_date: datetime,
    ) -> bool:
        """Return whether an unresolved row already holds this observation."""
        if not source_ref:
            return False
        try:
            identities = self.identity_service.recognition(
                bank=bank,
                account_id=upload.account_id,
                source_ref=source_ref,
            )
        except StatementFingerprintUnavailableError:
            return False
        digests = [identity.digest for identity in identities]
        if not digests:
            return False
        rows = BankStatementRow.objects.filter(
            upload__account=upload.account,
            source_fingerprint__in=digests,
            decision__in={
                BankStatementRow.Decision.PENDING,
                BankStatementRow.Decision.AWAITING_MARKUP,
                BankStatementRow.Decision.NEEDS_TRANSFER,
                BankStatementRow.Decision.MUTUAL_CANCEL,
            },
        ).exclude(upload=upload)
        return any(
            self._row_matches(
                row,
                type_value=type_value,
                amount=amount,
                trans_date=trans_date,
                match_calendar_date=True,
            )
            for row in rows
        )

    def _save_needs_transfer_row(
        self,
        *,
        upload: BankStatementUpload,
        trans: dict[str, Any],
        row_position: int,
        bank: str = 'generic',
        format_version: int = 1,
        source_ref_strength: str | None = None,
    ) -> None:
        """Save a credit-account credit as an unperformed repayment row."""
        fingerprint = self._fingerprint(
            upload=upload,
            bank=bank,
            source_ref=trans.get('source_ref'),
        )
        if source_ref_strength is None:
            source_ref_strength = _reference_strength(bank, trans)
        BankStatementRow.objects.get_or_create(
            upload=upload,
            source_row_position=row_position,
            defaults={
                'transaction_type': TransactionType.INCOME,
                'transaction_date': trans['date'],
                'amount': abs(trans['amount']),
                'description': strip_pii(str(trans['description']))[
                    : constants.TWO_HUNDRED_FIFTY
                ],
                'source_ref': trans.get('source_ref') or None,
                'source_ref_strength': source_ref_strength,
                'source_format_version': format_version,
                'source_fingerprint': (
                    fingerprint.digest if fingerprint else ''
                ),
                'source_fingerprint_key_version': (
                    fingerprint.key_version if fingerprint else ''
                ),
                'source_fingerprint_format_version': (
                    fingerprint.format_version if fingerprint else 0
                ),
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


def _mutual_cancel_positions(
    rows: dict[int, dict[str, Any]],
    *,
    excluded_positions: set[int] | None = None,
) -> set[int]:
    """Pair each cancel with a debit of the same device owner and amount.

    A position listed in ``excluded_positions`` is a repeat observation of
    an earlier upload, so automatic cancellation must leave both sides for
    the user instead of closing them silently.
    """
    skipped = excluded_positions or set()
    debits: dict[tuple[str, Decimal], list[int]] = {}
    for idx, trans in rows.items():
        if idx in skipped:
            continue
        if trans.get('kind') == RosDorBankRowKind.CARD and trans['amount'] < 0:
            debits.setdefault(
                (trans['description'], -trans['amount']),
                [],
            ).append(idx)
    positions: set[int] = set()
    for idx, trans in rows.items():
        if idx in skipped:
            continue
        if trans.get('kind') != RosDorBankRowKind.CANCEL:
            continue
        matches = debits.get((trans['description'], trans['amount']))
        if matches:
            positions |= {matches.pop(0), idx}
    return positions
