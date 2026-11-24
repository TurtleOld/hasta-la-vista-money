"""Verify a bank statement balance against the shared balance history.

The check compares the statement closing balance with
``BalanceHistoryService.balance_at`` only when the parser supplied a
confirmed currency and a confirmed moment semantics. A bank date without
confirmed closing semantics stays a date; no exact moment, currency or
zero is inferred. Explanations are controlled codes with an actor and an
audit entry; they never change money or make the balances equal.
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.services.protocols import (
    BalanceHistoryServiceProtocol,
)
from hasta_la_vista_money.system.models import AuditLog, AuditOperationKind
from hasta_la_vista_money.system.services.audit_context import (
    audit_operation,
    current_operation_id,
    current_operation_kind,
)
from hasta_la_vista_money.users.models import BankStatementUpload
from hasta_la_vista_money.users.services.statement_completion import (
    has_open_rows,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User

COMPLETE = 'complete'
INCOMPLETE = 'incomplete'

EXPLANATION_COMPLETENESS: dict[str, str] = {
    BankStatementUpload.ExplanationCode.BANK_POSTING_DATE_DIFFERENCE: COMPLETE,
    BankStatementUpload.ExplanationCode.CONSCIOUS_INCOMPLETE_ACCOUNTING: (
        INCOMPLETE
    ),
}

_CONFIRMED_SEMANTICS = {
    BankStatementUpload.BalanceType.EXACT_MOMENT,
    BankStatementUpload.BalanceType.CLOSING_DAY,
}


@dataclass(frozen=True)
class BalanceVerificationState:
    """One verified statement balance, independent of other measurements."""

    upload: BankStatementUpload
    checked: bool
    actual: bool
    result: str
    reason: str
    label: str
    detail: str
    moment: datetime | None
    bank_date: date | None
    type_label: str
    currency: str
    bank_balance: Decimal | None
    ledger_balance: Decimal | None
    discrepancy: Decimal | None
    has_amounts: bool
    can_explain: bool
    explanation_code: str
    explanation_label: str
    completeness: str
    explained_by: 'User | None'
    explained_at: datetime | None
    blocks_final_reconciliation: bool


class StatementBalanceVerificationService:
    """Compare statement balances and apply controlled explanations."""

    def __init__(
        self,
        balance_history_service: BalanceHistoryServiceProtocol,
    ) -> None:
        """Initialise the service with the shared balance history facade.

        Args:
            balance_history_service: Shared reconstruction of past balances.
        """
        self._balance_history_service = balance_history_service

    @staticmethod
    def _comparison_moment(
        upload: BankStatementUpload,
    ) -> datetime | None:
        """Return a comparison moment only from confirmed bank metadata.

        ``closing_day`` uses the bank's calendar day at end-of-day because
        the parser confirmed that meaning; the moment itself is not stored
        and is not invented for unknown semantics.
        """
        if upload.balance_type == BankStatementUpload.BalanceType.EXACT_MOMENT:
            return upload.balance_moment
        if (
            upload.balance_type == BankStatementUpload.BalanceType.CLOSING_DAY
            and upload.balance_bank_date is not None
        ):
            return timezone.make_aware(
                datetime.combine(upload.balance_bank_date, time.max),
            )
        return None

    def verify(self, upload: BankStatementUpload) -> BankStatementUpload:
        """Recompute and store the balance result for one upload.

        A failed comparison keeps the last proven result and its amounts,
        marks it stale and records why it cannot be confirmed now. Only an
        upload without a proven result becomes ``NOT_CHECKED`` with no
        amounts. The account currency is never copied into the statement
        currency.

        Args:
            upload: Statement upload whose closing balance is checked.

        Returns:
            The refreshed upload with its stored verification.
        """
        upload = BankStatementUpload.objects.select_related('account').get(
            pk=upload.pk,
        )
        if upload.retention_cleaned_at is not None:
            return upload
        with transaction.atomic():
            upload = (
                BankStatementUpload.objects.select_for_update()
                .select_related('account')
                .get(pk=upload.pk)
            )
            if upload.retention_cleaned_at is not None:
                return upload
            account = Account.objects.select_for_update().get(
                pk=upload.account_id,
            )
            upload.account = account
            return self._verify_locked(upload, account)

    def _verify_locked(
        self,
        upload: BankStatementUpload,
        account: Account,
    ) -> BankStatementUpload:
        """Compute and store a result while upload and account are locked."""
        account.refresh_from_db(fields=['balance', 'currency'])
        now = timezone.now()
        closing = upload.statement_closing_balance
        currency = upload.balance_currency
        kind = upload.balance_type
        moment = self._comparison_moment(upload)
        unresolved = has_open_rows(upload)
        reason = ''
        if unresolved:
            reason = BankStatementUpload.BalanceReason.UNRESOLVED_ROWS
        elif closing is None:
            reason = BankStatementUpload.BalanceReason.MISSING_BALANCE
        elif not currency:
            reason = BankStatementUpload.BalanceReason.MISSING_CURRENCY
        elif currency != account.currency:
            reason = BankStatementUpload.BalanceReason.CURRENCY_MISMATCH
        elif kind not in _CONFIRMED_SEMANTICS:
            reason = BankStatementUpload.BalanceReason.MISSING_SEMANTICS
        elif moment is None:
            reason = BankStatementUpload.BalanceReason.MISSING_MOMENT

        explanation_code = upload.balance_explanation_code
        explained_at = upload.balance_explained_at
        explained_by = upload.balance_explained_by
        if reason:
            # An impossible comparison is not evidence that a proven result
            # vanished: keep the snapshot, mark it stale and record the cause.
            result = upload.balance_result
            proven = result != BankStatementUpload.BalanceResult.NOT_CHECKED
            ledger = upload.account_balance_after if proven else None
            discrepancy = upload.balance_discrepancy if proven else None
            explanation_code = upload.balance_explanation_code if proven else ''
            explained_at = upload.balance_explained_at if proven else None
            explained_by = upload.balance_explained_by if proven else None
        elif closing is not None and currency and moment is not None:
            ledger = self._balance_history_service.balance_at(
                account,
                moment,
            )
            discrepancy = closing - ledger
            result = (
                BankStatementUpload.BalanceResult.MATCHED
                if discrepancy == Decimal(0)
                else BankStatementUpload.BalanceResult.DISCREPANCY
            )
            if (
                result != BankStatementUpload.BalanceResult.DISCREPANCY
                or discrepancy != upload.balance_discrepancy
            ):
                explanation_code = ''
                explained_at = None
                explained_by = None
        else:
            result = BankStatementUpload.BalanceResult.NOT_CHECKED
            ledger = None
            discrepancy = None
            explanation_code = ''
            explained_at = None
            explained_by = None

        BankStatementUpload.objects.filter(pk=upload.pk).update(
            balance_result=result,
            # A failed recheck keeps the date of the last confirmed
            # comparison instead of the time of the failed attempt.
            balance_checked_at=(
                upload.balance_checked_at
                if reason
                and upload.balance_result
                != BankStatementUpload.BalanceResult.NOT_CHECKED
                else now
            ),
            balance_is_actual=(
                not reason
                and result != BankStatementUpload.BalanceResult.NOT_CHECKED
            ),
            balance_reason=reason,
            account_balance_after=ledger,
            balance_discrepancy=discrepancy,
            balance_explanation_code=explanation_code,
            balance_explained_at=explained_at,
            balance_explained_by=explained_by,
        )
        return BankStatementUpload.objects.select_related(
            'account',
            'balance_explained_by',
        ).get(pk=upload.pk)

    def refresh_actuality(
        self,
        upload: BankStatementUpload,
    ) -> BankStatementUpload:
        """Mark a stored result stale if money, date or currency changed.

        The comparison is recomputed through the shared balance history
        facade, so a category-only edit leaves the result actual.

        Args:
            upload: Statement upload to inspect.

        Returns:
            The upload, refreshed after any staleness update.
        """
        upload = BankStatementUpload.objects.select_related('account').get(
            pk=upload.pk,
        )
        if not upload.balance_is_actual:
            return upload
        with transaction.atomic():
            upload = (
                BankStatementUpload.objects.select_for_update()
                .select_related('account')
                .get(pk=upload.pk)
            )
            if not upload.balance_is_actual:
                return upload
            account = Account.objects.select_for_update().get(
                pk=upload.account_id,
            )
            upload.account = account
            reason = self._stale_reason(upload, account)
            if reason:
                BankStatementUpload.objects.filter(pk=upload.pk).update(
                    balance_is_actual=False,
                    balance_reason=reason,
                )
                upload.balance_is_actual = False
                upload.balance_reason = reason
            return upload

    def _stale_reason(
        self,
        upload: BankStatementUpload,
        account: Account,
    ) -> str:
        """Return why a stored actual result is no longer current."""
        if (
            upload.balance_result
            == BankStatementUpload.BalanceResult.NOT_CHECKED
            or not upload.balance_currency
            or upload.balance_type not in _CONFIRMED_SEMANTICS
            or upload.account_balance_after is None
        ):
            return ''
        moment = self._comparison_moment(upload)
        if moment is None:
            return ''
        if upload.balance_currency != account.currency:
            return BankStatementUpload.BalanceReason.CURRENCY_CHANGED
        ledger = self._balance_history_service.balance_at(account, moment)
        if ledger != upload.account_balance_after:
            return BankStatementUpload.BalanceReason.MONEY_OR_DATE_CHANGED
        return ''

    def explain(
        self,
        upload: BankStatementUpload,
        user: 'User',
        code: str,
    ) -> BankStatementUpload:
        """Explain an actual discrepancy with an approved code.

        The explanation keeps its actor and time, writes an audit entry and
        never changes the balances or creates a movement. The upload and
        account are locked in the same order as statement markup so a
        concurrent movement edit cannot make an old snapshot actual.

        Args:
            upload: Statement upload with the unexplained discrepancy.
            user: Account owner recording the explanation.
            code: One of ``BankStatementUpload.ExplanationCode``.

        Returns:
            The upload with the recorded explanation.

        Raises:
            PermissionDenied: If the user does not own the account.
            ValidationError: If the code, result, actuality or source state
                does not allow an explanation.
        """
        if code not in BankStatementUpload.ExplanationCode.values:
            raise ValidationError(
                _('Объяснение допускается только утверждённым кодом.'),
            )
        with transaction.atomic():
            upload = (
                BankStatementUpload.objects.select_for_update()
                .select_related('account')
                .get(pk=upload.pk)
            )
            account = Account.objects.select_for_update().get(
                pk=upload.account_id,
            )
            upload.account = account
            if account.user_id != user.pk:
                raise PermissionDenied(
                    _('Расхождение объясняет только владелец счёта.'),
                )
            if upload.retention_cleaned_at is not None:
                raise ValidationError(
                    _('Банковские данные очищены: объяснение недоступно.'),
                )
            if upload.status == BankStatementUpload.Status.FAILED or (
                upload.error_message
            ):
                raise ValidationError(
                    _('Неразрешённая структурная ошибка файла не объясняется.'),
                )
            reason = self._stale_reason(upload, account)
            if reason or not upload.balance_is_actual:
                raise ValidationError(
                    _('Результат проверки устарел: перепроверьте остаток.'),
                )
            if (
                upload.balance_result
                != BankStatementUpload.BalanceResult.DISCREPANCY
            ):
                raise ValidationError(
                    _('Объяснение допускается только для расхождения остатка.'),
                )

            now = timezone.now()
            completeness = EXPLANATION_COMPLETENESS[code]
            with audit_operation(
                kind=AuditOperationKind.STATEMENT_IMPORT_RESOLUTION,
            ):
                BankStatementUpload.objects.filter(pk=upload.pk).update(
                    balance_explanation_code=code,
                    balance_explained_at=now,
                    balance_explained_by=user,
                )
                AuditLog.objects.create(
                    user=user,
                    model_name='users.BankStatementUpload',
                    object_pk=str(upload.pk),
                    object_name=account.name_account,
                    action=AuditLog.Action.UPDATE,
                    diff={
                        'explanation_code': code,
                        'completeness': completeness,
                    },
                    operation_id=current_operation_id(),
                    kind=current_operation_kind(),
                )
        return BankStatementUpload.objects.select_related(
            'account',
            'balance_explained_by',
        ).get(pk=upload.pk)

    @staticmethod
    def _detail_parts(upload: BankStatementUpload) -> list[str]:
        """Return confirmed moment/currency/date details for display."""
        parts: list[str] = []
        if upload.balance_bank_date is not None:
            parts.append(
                _('Дата остатка: %(date)s')
                % {'date': upload.balance_bank_date.strftime('%d.%m.%Y')},
            )
        if upload.balance_moment is not None:
            parts.append(
                _('Момент: %(moment)s')
                % {
                    'moment': timezone.localtime(
                        upload.balance_moment,
                    ).strftime('%d.%m.%Y %H:%M'),
                },
            )
        if upload.balance_currency:
            parts.append(
                _('Валюта: %(currency)s')
                % {'currency': upload.balance_currency},
            )
        if upload.balance_checked_at is not None:
            parts.append(
                _('Последняя проверка: %(checked)s')
                % {
                    'checked': timezone.localtime(
                        upload.balance_checked_at,
                    ).strftime('%d.%m.%Y %H:%M'),
                },
            )
        return parts

    def describe(
        self,
        upload: BankStatementUpload,
    ) -> BalanceVerificationState:
        """Describe one stored verification for the accounting control.

        Args:
            upload: Statement upload whose actuality has been refreshed.

        Returns:
            A user-facing state of the balance measurement.
        """
        checked = (
            upload.balance_result
            != BankStatementUpload.BalanceResult.NOT_CHECKED
        )
        actual = upload.balance_is_actual
        result = upload.balance_result
        explanation_code = upload.balance_explanation_code
        explanation_label = (
            str(upload.get_balance_explanation_code_display())
            if explanation_code
            else ''
        )
        completeness = EXPLANATION_COMPLETENESS.get(explanation_code, '')
        if not checked:
            label = _('Не проверено')
        elif not actual:
            label = _('Требует перепроверки')
        elif result == BankStatementUpload.BalanceResult.MATCHED:
            label = _('Совпадает')
        elif explanation_code:
            label = _('Расхождение объяснено')
        else:
            label = _('Расхождение')
        reason_label = (
            str(upload.get_balance_reason_display())
            if upload.balance_reason
            else ''
        )
        detail_parts = self._detail_parts(upload)
        if reason_label:
            detail_parts.append(reason_label)
        if explanation_label:
            detail_parts.append(explanation_label)
        blocks = result == BankStatementUpload.BalanceResult.DISCREPANCY and (
            not explanation_code
            or (
                not actual
                and upload.balance_reason
                != BankStatementUpload.BalanceReason.BANK_DATA_CLEANED
            )
        )
        return BalanceVerificationState(
            upload=upload,
            checked=checked,
            actual=actual,
            result=result,
            reason=upload.balance_reason,
            label=str(label),
            detail=' · '.join(str(part) for part in detail_parts),
            moment=upload.balance_moment,
            bank_date=upload.balance_bank_date,
            type_label=str(upload.get_balance_type_display()),
            currency=upload.balance_currency,
            bank_balance=upload.statement_closing_balance,
            ledger_balance=upload.account_balance_after,
            discrepancy=upload.balance_discrepancy,
            has_amounts=(
                upload.statement_closing_balance is not None
                and upload.account_balance_after is not None
            ),
            can_explain=(
                actual
                and result == BankStatementUpload.BalanceResult.DISCREPANCY
                and not explanation_code
                and upload.retention_cleaned_at is None
            ),
            explanation_code=explanation_code,
            explanation_label=explanation_label,
            completeness=completeness,
            explained_by=upload.balance_explained_by,
            explained_at=upload.balance_explained_at,
            blocks_final_reconciliation=blocks,
        )
