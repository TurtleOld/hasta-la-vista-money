"""One owner-scoped list of every unresolved statement problem."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money.users.accounting_types import (
    AccountingAccountOption,
    AccountingKnownTotal,
    AccountingProblemCounts,
    AccountingProblemFilter,
    AccountingProblemItem,
    AccountingProblemList,
    ProblemAction,
    ProblemKind,
    ProblemState,
    frozen_counts,
)
from hasta_la_vista_money.users.models import (
    UNRESOLVED_STATEMENT_DECISIONS,
    BankStatementRow,
    BankStatementUpload,
)
from hasta_la_vista_money.users.services.statement_date_policy import (
    statement_row_day,
)
from hasta_la_vista_money.users.services.statement_retention_policy import (
    row_has_bank_data,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

    from django.utils.functional import Promise

    from hasta_la_vista_money.finance_account.models import Account
    from hasta_la_vista_money.users.models import User
    from hasta_la_vista_money.users.protocols.accounting_completeness import (
        AccountingCompletenessServiceProtocol,
    )
    from hasta_la_vista_money.users.repositories.accounting_problem_repository import (  # noqa: E501
        AccountingProblemRepository,
    )


@dataclass(frozen=True)
class _RowProblem:
    """Kind, action and lazy user-facing reason of one row decision."""

    kind: str
    action: str
    reason: Promise


#: Lazy literals: makemessages extracts every reason, translation happens
#: per request, never at import time.
_ROW_PROBLEMS: Mapping[str, _RowProblem] = {
    BankStatementRow.Decision.DEFERRED: _RowProblem(
        ProblemKind.DEFERRED,
        ProblemAction.RECONCILE,
        _('Строка отложена и всё ещё ждёт решения'),
    ),
    # Legacy value: never written, migrated to ``deferred``.
    BankStatementRow.Decision.SKIPPED: _RowProblem(
        ProblemKind.DEFERRED,
        ProblemAction.RECONCILE,
        _('Строка отложена и всё ещё ждёт решения'),
    ),
    BankStatementRow.Decision.AWAITING_MARKUP: _RowProblem(
        ProblemKind.INCOMPLETE_MARKUP,
        ProblemAction.MARKUP,
        _('Строка выписки ещё не размечена'),
    ),
    BankStatementRow.Decision.PENDING: _RowProblem(
        ProblemKind.PROBABLE_DUPLICATE,
        ProblemAction.RECONCILE,
        _('Вероятный дубль ждёт решения; отсутствие движения не доказано'),
    ),
    BankStatementRow.Decision.NEEDS_TRANSFER: _RowProblem(
        ProblemKind.REPAYMENT,
        ProblemAction.ACCOUNTS,
        _('Погашение ещё не проведено переводом'),
    ),
    BankStatementRow.Decision.PARSE_ERROR: _RowProblem(
        ProblemKind.PARSE_ERROR,
        ProblemAction.RECONCILE,
        _('Операция не разобрана; неизвестные поля не заполнены'),
    ),
}
_PENDING_REASON = _('Строка ожидает решения')
_KIND_ORDER = {kind.value: index for index, kind in enumerate(ProblemKind)}
_KIND_ZERO = {kind.value: 0 for kind in ProblemKind}


@dataclass
class _Totals:
    values: dict[tuple[str, str], tuple[Decimal, int]]
    incomplete: bool


class AccountingProblemService:
    """Read one unified, owner-only snapshot of statement problems."""

    def __init__(
        self,
        repository: AccountingProblemRepository,
        completeness_service: (
            AccountingCompletenessServiceProtocol | None
        ) = None,
    ) -> None:
        self.repository = repository
        self.completeness_service = completeness_service

    def summary(self, owner: User) -> AccountingProblemCounts:
        """Return badge counters using the same list as the page."""
        return self.problems(owner).counts

    def problems(
        self,
        owner: User,
        *,
        account_ids: Sequence[int] = (),
        start: date | None = None,
        end: date | None = None,
        filters: AccountingProblemFilter | None = None,
    ) -> AccountingProblemList:
        active = self._validated_filters(
            owner,
            account_ids,
            start,
            end,
            filters,
        )
        selected_ids = tuple(account_ids)
        rows = list(
            self.repository.statement_rows(
                owner.pk,
                account_ids=selected_ids,
                bank_code=active.bank_code,
                currency=active.currency,
            ),
        )
        uploads = list(
            self.repository.uploads(
                owner.pk,
                account_ids=selected_ids,
                bank_code=active.bank_code,
                currency=active.currency,
            ),
        )
        accounts = list(self.repository.owner_accounts(owner.pk))
        items: list[AccountingProblemItem] = []
        recovery_rows: Counter[int] = Counter()
        # An exclusion carries no date of its own, so this caveat stays scoped
        # to the selected accounts, bank and currency only.
        excluded_reasons: Counter[str] = Counter()

        unresolved: list[tuple[BankStatementRow, str]] = []
        for row in rows:
            decision = row.decision
            if decision == BankStatementRow.Decision.EXCLUDED:
                reason = row.decision_reason or str(_('Без причины'))
                excluded_reasons[reason] += 1
                continue
            if decision not in UNRESOLVED_STATEMENT_DECISIONS:
                continue
            unresolved.append((row, decision))
            if self._row_is_recovery(row, decision):
                recovery_rows[row.upload_id] += 1
                continue
            self._append_row_item(items, row, decision)

        for upload in uploads:
            self._append_upload_items(
                items,
                upload,
                recovery_rows.get(upload.pk, 0),
            )
        balance_checked = self._append_balance_items(
            items,
            owner=owner,
            uploads=uploads,
            account_ids=selected_ids,
            start=start,
            end=end,
        )

        listed_rows = [
            (row, decision)
            for row, decision in unresolved
            if self._row_is_listed(row, decision, active, start, end)
        ]
        items = self._filtered_items(items, active, start, end)
        totals = self._totals_from_rows(listed_rows)
        counts = self._counts(
            items,
            listed_rows,
            excluded_reasons,
        )
        return AccountingProblemList(
            items=tuple(items),
            counts=counts,
            accounts=tuple(
                self._account_option(account) for account in accounts
            ),
            totals=self._known_totals(totals),
            totals_incomplete=totals.incomplete,
            excluded_reasons=tuple(sorted(excluded_reasons.items())),
            incomplete_reasons=(
                ()
                if balance_checked
                else ('balance_verification_not_integrated',)
            ),
        )

    def _validated_filters(
        self,
        owner: User,
        account_ids: Sequence[int],
        start: date | None,
        end: date | None,
        filters: AccountingProblemFilter | None,
    ) -> AccountingProblemFilter:
        if start is not None and end is not None and start > end:
            raise ValidationError(_('Начало периода позже его конца.'))
        requested = tuple(dict.fromkeys(account_ids))
        if requested:
            owned = self.repository.owned_account_ids(owner.pk, requested)
            if owned != set(requested):
                raise ValidationError(
                    _('Выбран счёт другого пользователя.'),
                )
        active = filters or AccountingProblemFilter()
        if active.kind and active.kind not in _KIND_ZERO:
            raise ValidationError(_('Неизвестный вид проблемы учёта.'))
        if active.state not in {state.value for state in ProblemState}:
            raise ValidationError(_('Неизвестное состояние проблемы учёта.'))
        return active

    @staticmethod
    def _has_duplicate_evidence(row: BankStatementRow) -> bool:
        """Only a stored candidate or exact-duplicate link is evidence."""
        return bool(
            row.candidate_id is not None
            or row.duplicate_of_id is not None
            or getattr(row, 'has_candidate', False),
        )

    @staticmethod
    def _row_date(row: BankStatementRow) -> date | None:
        """Return the row's bank day, or ``None`` when it has no date."""
        return statement_row_day(row)

    def _append_row_item(
        self,
        items: list[AccountingProblemItem],
        row: BankStatementRow,
        decision: str,
    ) -> None:
        if decision == BankStatementRow.Decision.PENDING and not (
            self._has_duplicate_evidence(row)
        ):
            problem = _RowProblem(
                ProblemKind.UNRESOLVED,
                ProblemAction.RECONCILE,
                _PENDING_REASON,
            )
        else:
            problem = _ROW_PROBLEMS[decision]
        items.append(
            self._item(
                kind=problem.kind,
                action=problem.action,
                upload_id=row.upload_id,
                row_id=row.pk,
                upload=row.upload,
                transaction_date=self._row_date(row),
                amount=row.amount,
                description=row.description,
                reason=str(problem.reason),
                data_available=True,
                direction=row.transaction_type or '',
            ),
        )

    def _append_upload_items(
        self,
        items: list[AccountingProblemItem],
        upload: BankStatementUpload,
        recovery_count: int,
    ) -> None:
        if recovery_count:
            items.append(
                self._item(
                    kind=ProblemKind.RECOVERY,
                    action=ProblemAction.UPLOAD,
                    upload_id=upload.pk,
                    row_id=None,
                    upload=upload,
                    transaction_date=None,
                    amount=None,
                    description='',
                    reason=str(
                        _(
                            'Банковские данные удалены по сроку; '
                            'требуется повторная загрузка',
                        ),
                    ),
                    data_available=False,
                    row_count=recovery_count,
                ),
            )
        if upload.status == BankStatementUpload.Status.FAILED:
            items.append(
                self._item(
                    kind=ProblemKind.UPLOAD_FAILED,
                    action=ProblemAction.UPLOAD,
                    upload_id=upload.pk,
                    row_id=None,
                    upload=upload,
                    transaction_date=None,
                    amount=None,
                    description='',
                    reason=str(
                        _('Загрузка выписки завершилась ошибкой'),
                    ),
                    data_available=False,
                ),
            )

    def _append_balance_items(
        self,
        items: list[AccountingProblemItem],
        *,
        owner: User,
        uploads: list[BankStatementUpload],
        account_ids: Sequence[int],
        start: date | None,
        end: date | None,
    ) -> bool:
        """Project ticket 09's retained guard through the 08 assessment.

        Returns whether the balance verification provider is wired. The
        service never reads the legacy current-balance discrepancy as a
        substitute for the retained 09 flag.
        """
        if self.completeness_service is None:
            return False
        projection = self.completeness_service.balance_block(
            owner=owner,
            account_ids=tuple(account_ids) or None,
            period_start=start,
            period_end=end,
        )
        block = projection.block
        upload_ids = getattr(block, 'upload_ids', ())
        uploads_by_id = {upload.pk: upload for upload in uploads}
        for upload_id in upload_ids:
            upload = uploads_by_id.get(upload_id)
            if upload is None:
                continue
            items.append(
                self._item(
                    kind=ProblemKind.BALANCE_ATTENTION,
                    action=ProblemAction.UPLOAD,
                    upload_id=upload.pk,
                    row_id=None,
                    upload=upload,
                    transaction_date=None,
                    amount=None,
                    description=str(
                        _('Расхождение с остатком выписки'),
                    ),
                    reason=str(
                        _(
                            'Известное необъяснённое расхождение остатка; '
                            'требуется решение пользователя',
                        ),
                    ),
                    data_available=True,
                ),
            )
        return projection.checked

    def _item(
        self,
        *,
        kind: str,
        action: str,
        upload_id: int,
        row_id: int | None,
        upload: BankStatementUpload,
        transaction_date: date | None,
        amount: Decimal | None,
        description: str,
        reason: str,
        data_available: bool,
        row_count: int = 1,
        direction: str = '',
    ) -> AccountingProblemItem:
        account = upload.account
        return AccountingProblemItem(
            kind=kind,
            action=action,
            upload_id=upload_id,
            row_id=row_id,
            account_id=account.pk,
            account_name=account.name_account,
            bank_code=account.bank.code,
            bank_name=account.bank.name,
            currency=account.currency,
            transaction_date=transaction_date,
            date_known=transaction_date is not None,
            amount=amount,
            amount_known=amount is not None,
            description=description,
            reason=reason,
            row_count=row_count,
            data_available=data_available,
            direction=direction,
        )

    @staticmethod
    def _row_is_recovery(row: BankStatementRow, decision: str) -> bool:
        """Tell whether an unresolved row lost its statement details."""
        return decision == BankStatementRow.Decision.EXPIRED or not (
            row_has_bank_data(row)
        )

    def _row_is_listed(
        self,
        row: BankStatementRow,
        decision: str,
        active: AccountingProblemFilter,
        start: date | None,
        end: date | None,
    ) -> bool:
        """Apply the page filters to one row, exactly as to its item."""
        if active.kind and self._row_problem_kind(row, decision) != active.kind:
            return False
        recovery = self._row_is_recovery(row, decision)
        if active.state == ProblemState.RECOVERY and not recovery:
            return False
        if active.state == ProblemState.AVAILABLE and recovery:
            return False
        day = self._row_date(row)
        if start is not None and day is not None and day < start:
            return False
        return not (end is not None and day is not None and day > end)

    def _row_problem_kind(self, row: BankStatementRow, decision: str) -> str:
        """Return the problem kind a row contributes to the list."""
        if self._row_is_recovery(row, decision):
            return ProblemKind.RECOVERY
        if decision == BankStatementRow.Decision.PENDING and not (
            self._has_duplicate_evidence(row)
        ):
            return ProblemKind.UNRESOLVED
        return _ROW_PROBLEMS[decision].kind

    @staticmethod
    def _totals_from_rows(
        rows: Sequence[tuple[BankStatementRow, str]],
    ) -> _Totals:
        """Sum the listed rows, so totals and the list share one scope."""
        values: dict[tuple[str, str], tuple[Decimal, int]] = {}
        incomplete = False
        for row, _decision in rows:
            if row.amount is None or not row.transaction_type:
                incomplete = True
                continue
            key = (row.upload.account.currency, row.transaction_type)
            amount, count = values.get(key, (Decimal(0), 0))
            values[key] = (amount + row.amount, count + 1)
        return _Totals(values=values, incomplete=incomplete)

    def _filtered_items(
        self,
        items: list[AccountingProblemItem],
        active: AccountingProblemFilter,
        start: date | None,
        end: date | None,
    ) -> list[AccountingProblemItem]:
        if active.kind:
            items = [item for item in items if item.kind == active.kind]
        if active.state == ProblemState.RECOVERY:
            items = [
                item for item in items if item.kind == ProblemKind.RECOVERY
            ]
        elif active.state == ProblemState.AVAILABLE:
            items = [item for item in items if item.data_available]
        if start is not None:
            items = [
                item
                for item in items
                if item.transaction_date is None
                or item.transaction_date >= start
            ]
        if end is not None:
            items = [
                item
                for item in items
                if item.transaction_date is None or item.transaction_date <= end
            ]
        return sorted(items, key=self._sort_key)

    @staticmethod
    def _sort_key(
        item: AccountingProblemItem,
    ) -> tuple[bool, int, int, int, int]:
        return (
            item.transaction_date is None,
            -item.transaction_date.toordinal()
            if item.transaction_date is not None
            else 0,
            _KIND_ORDER[item.kind],
            item.upload_id,
            item.row_id or 0,
        )

    @staticmethod
    def _counts(
        items: Sequence[AccountingProblemItem],
        listed_rows: Sequence[tuple[BankStatementRow, str]],
        excluded_reasons: Counter[str],
    ) -> AccountingProblemCounts:
        """Count only what the page lists, plus the exclusion caveat."""
        by_kind = dict(_KIND_ZERO)
        for item in items:
            by_kind[item.kind] += 1
        recovery_row_count = sum(
            item.row_count
            for item in items
            if item.kind == ProblemKind.RECOVERY
        )
        unresolved_row_count = len(listed_rows)
        return frozen_counts(
            total_items=len(items),
            by_kind=by_kind,
            recovery_row_count=recovery_row_count,
            excluded_row_count=sum(excluded_reasons.values()),
            unresolved_row_count=unresolved_row_count,
        )

    @staticmethod
    def _account_option(account: Account) -> AccountingAccountOption:
        return AccountingAccountOption(
            id=account.pk,
            name=account.name_account,
            bank_code=account.bank.code,
            bank_name=account.bank.name,
            currency=account.currency,
        )

    @staticmethod
    def _known_totals(totals: _Totals) -> tuple[AccountingKnownTotal, ...]:
        return tuple(
            AccountingKnownTotal(
                currency=currency,
                direction=direction,
                amount=amount,
                row_count=count,
            )
            for (currency, direction), (amount, count) in sorted(
                totals.values.items(),
            )
        )
