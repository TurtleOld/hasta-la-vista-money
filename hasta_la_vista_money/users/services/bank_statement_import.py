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
    StatementParseResult,
)
from hasta_la_vista_money.users.services.pii_stripper import strip_pii
from hasta_la_vista_money.users.services.statement_identity import (
    StatementFingerprint,
    StatementFingerprintUnavailableError,
    StatementIdentityService,
)

if TYPE_CHECKING:
    from decimal import Decimal

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

        unsafe_identity = self._fingerprints_are_unsafe(upload)
        if parse_result.requires_markup or unsafe_identity:
            self._save_markup_rows(
                upload,
                transactions,
                parse_result,
                recognize_known=not unsafe_identity,
            )
            upload.refresh_from_db()
            if parse_result.requires_markup:
                self.coverage_service.record_statement_period(
                    upload,
                    parse_result.period_start,
                    parse_result.period_end,
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
            ) = self._process_transactions(
                upload=upload,
                transactions=transactions,
                existing_categories=existing_categories,
                parse_result=parse_result,
            )
            upload.refresh_from_db()

        self.coverage_service.record_statement_period(
            upload,
            parse_result.period_start,
            parse_result.period_end,
        )
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

    def _process_transactions(
        self,
        upload: BankStatementUpload,
        transactions: list[dict[str, Any]],
        existing_categories: list[str],
        parse_result: StatementParseResult | None = None,
    ) -> tuple[int, int, int, int]:
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

        Returns:
            Кортеж ``(income_count, expense_count, skipped_count,
            needs_transfer_count)``.
        """
        income_count = upload.income_count
        expense_count = upload.expense_count
        skipped_count = upload.skipped_count
        needs_transfer_count = upload.needs_transfer_count
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
            match_calendar_date = source == 'ozon' or bank == 'ozon'
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

            exact = None
            if source_ref not in ambiguous_refs:
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
                    source_ref_strength=trans.get(
                        'source_ref_strength',
                        'weak',
                    ),
                )

            # The classifier is a network call: keep it out of the row
            # transaction so a slow model does not hold it open.
            category_name = trans.get('category_name')
            if (
                category_name is None
                and not is_credit_income
                and not (exact is not None and not exact.conflict)
            ):
                category_name = self._classify_category(
                    strip_pii(str(description)),
                    type_value,
                    existing_categories,
                )

            with transaction.atomic():
                upload = self._lock_upload(upload.pk)
                if upload.processed_transactions > idx:
                    income_count = upload.income_count
                    expense_count = upload.expense_count
                    skipped_count = upload.skipped_count
                    needs_transfer_count = upload.needs_transfer_count
                    continue
                upload = self._lock_account(upload)
                exact = None
                if source_ref not in ambiguous_refs:
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
                        source_ref_strength=trans.get(
                            'source_ref_strength',
                            'weak',
                        ),
                    )
                if is_credit_income:
                    self._save_needs_transfer_row(
                        upload=upload,
                        trans=trans,
                        row_position=row_position,
                        bank=bank,
                        format_version=format_version,
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
                    )
                    if saved.decision == BankStatementRow.Decision.DUPLICATE:
                        skipped_count += 1
                else:
                    row_category = str(category_name or FALLBACK_CATEGORY)
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
                        )
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
        """Return the active fingerprint, or None when keys are unavailable."""
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

        A bank identifier is only a hint: the existing row or movement must
        also match the direction, amount and bank date. An unknown key or a
        missing fingerprint means no proof, never a negative conclusion.
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
        if source_ref:
            return None
        return self._exact_by_position(
            upload=upload,
            row_position=row_position,
            format_version=format_version,
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
    ) -> ExactObservation | None:
        """Return a position match, or a parser/format drift conflict."""
        existing = Transaction.objects.filter(
            account=upload.account,
            source_file_hash=upload.file_hash,
            source_row_position=row_position,
        )
        if not existing.exists():
            return None
        matching = existing.filter(source_format_version=format_version)
        if matching.exists():
            return ExactObservation(transaction=matching.first())
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
    ) -> BankStatementRow:
        """Record an exact repeat without touching money."""
        fingerprint = self._fingerprint(
            upload=upload,
            bank=bank,
            source_ref=trans.get('source_ref'),
        )
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
    ) -> BankStatementRow:
        """Create one row that records an observation without money."""
        row, _created = BankStatementRow.objects.get_or_create(
            upload=upload,
            source_row_position=row_position,
            defaults={
                'transaction_type': type_value,
                'transaction_date': trans['date'],
                'amount': abs(trans['amount']),
                'description': strip_pii(str(trans['description']))[
                    : constants.TWO_HUNDRED_FIFTY
                ],
                'source_ref': trans.get('source_ref') or None,
                'canonical_row': canonical_row,
                'transaction': transaction,
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
        return row

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
        parse_result: StatementParseResult,
        *,
        recognize_known: bool,
    ) -> None:
        """Save rows awaiting user markup; none of them is posted.

        When fingerprint keys are usable, rows already proven on the
        account become exact duplicate observations. Without usable keys
        every row is saved for manual resolution: a missing key never
        turns into "the operation does not exist" or auto-posting.
        """
        bank = parse_result.bank
        format_version = parse_result.format_version
        with transaction.atomic():
            upload = self._lock_upload(upload.pk)
            upload = self._lock_account(upload)
            new_rows: dict[int, dict[str, Any]] = {}
            duplicates: list[tuple[dict[str, Any], int, ExactObservation]] = []
            for idx, trans in enumerate(transactions):
                if recognize_known:
                    exact = self._find_exact_observation(
                        upload=upload,
                        bank=bank,
                        source_ref=trans.get('source_ref'),
                        row_position=idx,
                        type_value=(
                            TransactionType.INCOME
                            if trans['amount'] > 0
                            else TransactionType.EXPENSE
                        ),
                        amount=abs(trans['amount']),
                        trans_date=trans['date'],
                        match_calendar_date=True,
                        format_version=format_version,
                        source_ref_strength=trans.get(
                            'source_ref_strength',
                            'weak',
                        ),
                    )
                    if exact is not None and not exact.conflict:
                        duplicates.append((trans, idx, exact))
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
                        continue
                new_rows[idx] = trans
            # A cancel of a debit from an earlier upload is an income to
            # mark up.
            cancelled = _mutual_cancel_positions(new_rows)
            rows = []
            for idx, trans in new_rows.items():
                fingerprint = self._fingerprint(
                    upload=upload,
                    bank=bank,
                    source_ref=trans.get('source_ref'),
                )
                rows.append(
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
                        source_ref=trans.get('source_ref'),
                        source_row_position=idx,
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
                        match_calendar_date=True,
                        kind=str(trans.get('kind', '')),
                        merchant_key=trans.get('merchant_key') or '',
                        counterparty_account=(
                            trans.get('counterparty_account') or ''
                        ),
                        decision=(
                            BankStatementRow.Decision.MUTUAL_CANCEL
                            if idx in cancelled
                            else BankStatementRow.Decision.AWAITING_MARKUP
                        ),
                    ),
                )
            # A rerun of the same upload hits the per-upload row
            # constraint.
            BankStatementRow.objects.bulk_create(rows, ignore_conflicts=True)
            for trans, idx, exact in duplicates:
                self._save_duplicate_row(
                    upload=upload,
                    trans=trans,
                    row_position=idx,
                    type_value=(
                        TransactionType.INCOME
                        if trans['amount'] > 0
                        else TransactionType.EXPENSE
                    ),
                    observation=exact,
                    bank=bank,
                    format_version=format_version,
                )
            upload.processed_transactions = len(transactions)
            upload.skipped_count = len(transactions) - len(rows)
            upload.progress = 100
            upload.save(
                update_fields=[
                    'processed_transactions',
                    'skipped_count',
                    'progress',
                    'updated_at',
                ],
            )

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
    ) -> None:
        """Save a credit-account credit as an unperformed repayment row."""
        fingerprint = self._fingerprint(
            upload=upload,
            bank=bank,
            source_ref=trans.get('source_ref'),
        )
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


def _mutual_cancel_positions(rows: dict[int, dict[str, Any]]) -> set[int]:
    """Pair each cancel with a debit of the same device owner and amount."""
    debits: dict[tuple[str, Decimal], list[int]] = {}
    for idx, trans in rows.items():
        if trans.get('kind') == RosDorBankRowKind.CARD and trans['amount'] < 0:
            debits.setdefault(
                (trans['description'], -trans['amount']),
                [],
            ).append(idx)
    positions: set[int] = set()
    for idx, trans in rows.items():
        if trans.get('kind') != RosDorBankRowKind.CANCEL:
            continue
        matches = debits.get((trans['description'], trans['amount']))
        if matches:
            positions |= {matches.pop(0), idx}
    return positions
