"""Verify a bank statement balance against the shared balance history.

The check compares the statement closing balance with
``BalanceHistoryService.balance_at`` at the same moment and in one
currency. Missing data is never replaced with zero or with the current
balance. Explanations are controlled codes with an actor and an audit
entry; they never change money or make the balances equal.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

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
    type_label: str
    currency: str
    bank_balance: Decimal | None
    ledger_balance: Decimal | None
    discrepancy: Decimal | None
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

    def verify(self, upload: BankStatementUpload) -> BankStatementUpload:
        """Recompute and store the balance result for one upload.

        Missing closing balance, moment or currency produce
        ``NOT_CHECKED`` with no amounts; none of them is substituted.

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
        account = upload.account
        account.refresh_from_db(fields=['balance', 'currency'])
        now = timezone.now()
        closing = upload.statement_closing_balance
        moment = upload.balance_moment
        reason = ''
        if closing is None:
            reason = BankStatementUpload.BalanceReason.MISSING_BALANCE
        elif moment is None:
            reason = BankStatementUpload.BalanceReason.MISSING_MOMENT
        elif not account.currency:
            reason = BankStatementUpload.BalanceReason.MISSING_CURRENCY

        explanation_code = upload.balance_explanation_code
        explained_at = upload.balance_explained_at
        explained_by = upload.balance_explained_by
        if closing is not None and moment is not None and account.currency:
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
            balance_type=BankStatementUpload.BalanceType.CLOSING,
            balance_currency=account.currency,
            balance_result=result,
            balance_checked_at=now,
            balance_is_actual=True,
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
        if (
            not upload.balance_is_actual
            or upload.balance_result
            == BankStatementUpload.BalanceResult.NOT_CHECKED
            or upload.balance_moment is None
            or not upload.balance_currency
            or upload.account_balance_after is None
        ):
            return upload
        account = upload.account
        account.refresh_from_db(fields=['balance', 'currency'])
        reason = ''
        if upload.balance_currency != account.currency:
            reason = BankStatementUpload.BalanceReason.CURRENCY_CHANGED
        else:
            ledger = self._balance_history_service.balance_at(
                account,
                upload.balance_moment,
            )
            if ledger != upload.account_balance_after:
                reason = BankStatementUpload.BalanceReason.MONEY_OR_DATE_CHANGED
        if reason:
            BankStatementUpload.objects.filter(pk=upload.pk).update(
                balance_is_actual=False,
                balance_reason=reason,
            )
            upload.balance_is_actual = False
            upload.balance_reason = reason
        return upload

    def explain(
        self,
        upload: BankStatementUpload,
        user: 'User',
        code: str,
    ) -> BankStatementUpload:
        """Explain an actual discrepancy with an approved code.

        The explanation keeps its actor and time, writes an audit entry and
        never changes the balances or creates a movement.

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
        upload = BankStatementUpload.objects.select_related('account').get(
            pk=upload.pk,
        )
        if upload.account.user_id != user.pk:
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
        upload = self.refresh_actuality(upload)
        if not upload.balance_is_actual:
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
        with (
            transaction.atomic(),
            audit_operation(
                kind=AuditOperationKind.STATEMENT_IMPORT_RESOLUTION,
            ),
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
                object_name=upload.account.name_account,
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
        detail_parts = []
        if upload.balance_moment is not None:
            detail_parts.append(
                _('Момент: %(moment)s')
                % {
                    'moment': timezone.localtime(
                        upload.balance_moment,
                    ).strftime('%d.%m.%Y %H:%M'),
                },
            )
        if upload.balance_currency:
            detail_parts.append(
                _('Валюта: %(currency)s')
                % {'currency': upload.balance_currency},
            )
        if upload.balance_checked_at is not None:
            detail_parts.append(
                _('Последняя проверка: %(checked)s')
                % {
                    'checked': timezone.localtime(
                        upload.balance_checked_at,
                    ).strftime('%d.%m.%Y %H:%M'),
                },
            )
        if reason_label:
            detail_parts.append(reason_label)
        if explanation_label:
            detail_parts.append(explanation_label)
        blocks = result == BankStatementUpload.BalanceResult.DISCREPANCY and (
            not actual or not explanation_code
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
            type_label=str(upload.get_balance_type_display()),
            currency=upload.balance_currency,
            bank_balance=upload.statement_closing_balance,
            ledger_balance=upload.account_balance_after,
            discrepancy=upload.balance_discrepancy,
            explanation_code=explanation_code,
            explanation_label=explanation_label,
            completeness=completeness,
            explained_by=upload.balance_explained_by,
            explained_at=upload.balance_explained_at,
            blocks_final_reconciliation=blocks,
        )
