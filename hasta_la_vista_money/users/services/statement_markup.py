from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final, cast

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.translation import gettext as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.core.calendar_days import (
    filter_calendar_range,
    movement_calendar_date,
)
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.finance_account.repositories import (
    AccountRepository,
    TransferMoneyLogRepository,
)
from hasta_la_vista_money.finance_account.services.balance_service import (
    BalanceService,
)
from hasta_la_vista_money.finance_account.services.financial_change_hooks import (  # noqa: E501
    note_financial_change,
)
from hasta_la_vista_money.finance_account.services.protocols import (
    AccountCoverageServiceProtocol,
)
from hasta_la_vista_money.finance_account.validators import (
    validate_same_currency,
)
from hasta_la_vista_money.receipts.models import OPERATION_TYPES, Receipt
from hasta_la_vista_money.receipts.services.receipt_creator import (
    receipt_balance_delta,
)
from hasta_la_vista_money.system.models import AuditOperationKind
from hasta_la_vista_money.system.services.audit_context import audit_operation
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import (
    BankStatementDecisionAudit,
    BankStatementRow,
    BankStatementUpload,
    MerchantCategory,
    User,
)
from hasta_la_vista_money.users.protocols.statement_balance_verification import (  # noqa: E501
    StatementBalanceVerificationServiceProtocol,
)
from hasta_la_vista_money.users.repositories.statement_row_repository import (
    StatementRowRepository,
)
from hasta_la_vista_money.users.repositories.transfer_matching import (
    TRANSFER_DATE_WINDOW,
    local_row_date,
)
from hasta_la_vista_money.users.services.bank_statement import (
    RosDorBankRowKind,
)
from hasta_la_vista_money.users.services.bank_statement_reconciliation import (
    BankStatementReconciliationService,
)
from hasta_la_vista_money.users.services.statement_date_policy import (
    statement_row_calendar_date,
    statement_row_movement_date,
)
from hasta_la_vista_money.users.services.statement_retention_policy import (
    row_has_bank_data,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.transactions.managers import TransactionQuerySet

REFUND_CATEGORY_NAME: Final = 'Возвраты'
_NO_MERCHANT_KINDS: Final = frozenset(
    {RosDorBankRowKind.C2C, RosDorBankRowKind.OWN_C2C},
)


_transaction_manager = cast('TransactionQuerySet', Transaction.objects)


class StatementMarkupConflictError(ValueError):
    """Raised when a row cannot be marked up as requested."""


class StatementMarkupService:
    """Post or skip RosDorBank statement rows after user markup."""

    def __init__(
        self,
        balance_service: BalanceService,
        account_repository: AccountRepository,
        transfer_log_repository: TransferMoneyLogRepository,
        statement_row_repository: StatementRowRepository,
        *,
        coverage_service: AccountCoverageServiceProtocol,
        balance_verification: (
            StatementBalanceVerificationServiceProtocol | None
        ) = None,
    ) -> None:
        self._balance_service = balance_service
        self._account_repository = account_repository
        self._transfer_log_repository = transfer_log_repository
        self._statement_row_repository = statement_row_repository
        self._coverage_service = coverage_service
        self._balance_verification = balance_verification

    @staticmethod
    def pending_rows(upload: BankStatementUpload) -> QuerySet[BankStatementRow]:
        return BankStatementRow.objects.filter(
            upload=upload,
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
        ).order_by('transaction_date', 'pk')

    @staticmethod
    def pending_summary(user_id: int) -> tuple[int, int | None]:
        """Return rows awaiting markup in the newest upload and its id."""
        rows = BankStatementRow.objects.filter(
            StatementRowRepository.bank_data_available_q(),
            upload__user_id=user_id,
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
        )
        newest = (
            rows.order_by('-upload_id')
            .values_list('upload_id', flat=True)
            .first()
        )
        if newest is None:
            return 0, None
        return rows.filter(upload_id=newest).count(), newest

    @staticmethod
    def categories(user: User, transaction_type: str) -> list[Category]:
        """Return the user's categories in alphabetical order."""
        return list(
            Category.objects.filter(
                user=user,
                type=transaction_type,
                system_kind='',
            ).order_by('name'),
        )

    def probable_duplicates(
        self,
        upload: BankStatementUpload,
    ) -> dict[int, str]:
        """Map pending rows to a movement already recorded by hand.

        A movement is a transaction without ``source_ref`` or a receipt of
        the same day, type and amount, or a free mirroring transfer; each
        one matches at most one row.
        """
        rows = [
            (row, statement_row_calendar_date(row))
            for row in self.pending_rows(upload)
            if row.transaction_date is not None
        ]
        if not rows:
            return {}
        start = min(day for _row, day in rows) - TRANSFER_DATE_WINDOW
        end = max(day for _row, day in rows) + TRANSFER_DATE_WINDOW
        account_id = upload.account_id
        movements: list[tuple[str, Decimal, date, timedelta, str]] = [
            (
                movement.type,
                movement.amount,
                movement_calendar_date(
                    movement.date,
                    movement.bank_calendar_date,
                ),
                timedelta(0),
                str(movement.category.name),
            )
            for movement in filter_calendar_range(
                _transaction_manager.without_adjustments().filter(
                    account_id=account_id,
                    source_ref__isnull=True,
                    source_ref_hash__isnull=True,
                ),
                start,
                end,
            )
            .select_related('category')
            .order_by('date', 'pk')
        ]
        occupied = BankStatementRow.objects.filter(
            transfer__isnull=False,
            upload__account_id=account_id,
        ).values('transfer_id')
        movements.extend(
            (
                TransactionType.EXPENSE
                if transfer.from_account_id == account_id
                else TransactionType.INCOME,
                transfer.amount,
                movement_calendar_date(
                    transfer.exchange_date,
                    transfer.bank_calendar_date,
                ),
                TRANSFER_DATE_WINDOW,
                _('Перевод: {source} → {target}')
                .format(
                    source=getattr(transfer.from_account, 'name_account', ''),
                    target=getattr(transfer.to_account, 'name_account', ''),
                )
                .strip(' →'),
            )
            for transfer in filter_calendar_range(
                TransferMoneyLog.objects.filter(
                    Q(from_account_id=account_id) | Q(to_account_id=account_id),
                    user_id=upload.user_id,
                ),
                start,
                end,
                field='exchange_date',
            )
            .exclude(pk__in=occupied)
            .select_related('from_account', 'to_account')
            .order_by('exchange_date', 'pk')
        )
        movements.extend(
            (
                TransactionType.INCOME
                if receipt_balance_delta(receipt.operation_type, Decimal(1)) > 0
                else TransactionType.EXPENSE,
                receipt.total_sum,
                local_row_date(receipt.receipt_date),
                timedelta(0),
                _('Чек: {seller}')
                .format(seller=getattr(receipt.seller, 'name_seller', ''))
                .strip(' :'),
            )
            for receipt in Receipt.objects.filter(
                account_id=account_id,
                user_id=upload.user_id,
                operation_type__in=[value for value, _label in OPERATION_TYPES],
                receipt_date__date__range=(start, end),
            )
            .select_related('seller')
            .order_by('receipt_date', 'pk')
        )
        duplicates: dict[int, str] = {}
        for row, day in rows:
            for idx, (kind, amount, moment, window, label) in enumerate(
                movements,
            ):
                if (
                    kind == row.transaction_type
                    and amount == row.amount
                    and abs(moment - day) <= window
                ):
                    duplicates[row.pk] = label
                    del movements[idx]
                    break
        return duplicates

    def remembered_categories(
        self,
        upload: BankStatementUpload,
    ) -> dict[int, int]:
        """Map pending row ids to the category remembered for their key."""
        rows = list(
            self.pending_rows(upload)
            .exclude(merchant_key='')
            .values_list('pk', 'merchant_key', 'transaction_type'),
        )
        remembered: dict[tuple[str, str | None], int] = {
            (key, transaction_type): category_id
            for key, transaction_type, category_id in (
                MerchantCategory.objects.filter(
                    user_id=upload.user_id,
                    merchant_key__in={key for _, key, _ in rows},
                ).values_list('merchant_key', 'transaction_type', 'category_id')
            )
        }
        return {
            pk: remembered[key, transaction_type]
            for pk, key, transaction_type in rows
            if (key, transaction_type) in remembered
        }

    def post(
        self,
        row_id: int,
        user_id: int,
        category_id: int | None,
    ) -> BankStatementRow:
        """Post the row as a movement now, as one markup operation."""
        with audit_operation(kind=AuditOperationKind.STATEMENT_MARKUP):
            return self._decide(row_id, user_id, category_id, skip=False)

    @transaction.atomic
    def post_many(
        self,
        row_ids: list[int],
        user_id: int,
        category_id: int | None,
    ) -> list[BankStatementRow]:
        """Post rows of one direction with one category, all or nothing."""
        rows = BankStatementRow.objects.filter(
            pk__in=row_ids,
            upload__user_id=user_id,
        )
        kinds = {row.kind for row in rows}
        types = {row.transaction_type for row in rows}
        if (
            not row_ids
            or len(rows) != len(set(row_ids))
            or len(types) != 1
            or RosDorBankRowKind.OWN_C2C in kinds
        ):
            raise StatementMarkupConflictError('selection')
        with audit_operation(kind=AuditOperationKind.STATEMENT_MARKUP):
            return [
                self._decide(row_id, user_id, category_id, skip=False)
                for row_id in row_ids
            ]

    def post_remembered(
        self,
        upload_id: int,
        user_id: int,
    ) -> tuple[int, int]:
        """Post rows with a remembered category as one operation.

        Returns the posted and the skipped (conflicting) row counts.
        """
        upload = BankStatementUpload.objects.get(pk=upload_id, user_id=user_id)
        remembered = self.remembered_categories(upload)
        duplicates = self.probable_duplicates(upload)
        posted = 0
        with audit_operation(kind=AuditOperationKind.STATEMENT_MARKUP):
            for row_id, category_id in remembered.items():
                if row_id in duplicates:
                    continue
                try:
                    self._decide(
                        row_id,
                        user_id,
                        category_id,
                        skip=False,
                        finalize=False,
                    )
                except StatementMarkupConflictError:
                    continue
                posted += 1
            if posted:
                self._finalize(upload)
        return posted, len(remembered) - posted

    def decide_many(
        self,
        upload_id: int,
        user_id: int,
        decisions: dict[int, tuple[str, int | None]],
    ) -> tuple[int, int]:
        """Apply per-row decisions of the markup page as one operation.

        A decision is ``('post', category_id)``, ``('transfer', account_id)``
        or ``('defer', None)``; the legacy ``'skip'`` key means the same.
        Returns the decided and the failed row counts.
        """
        upload = BankStatementUpload.objects.get(pk=upload_id, user_id=user_id)
        pending = set(
            self.pending_rows(upload)
            .filter(pk__in=decisions)
            .values_list('pk', flat=True),
        )
        decided = 0
        with audit_operation(kind=AuditOperationKind.STATEMENT_MARKUP):
            for row_id, (decision, value) in decisions.items():
                if row_id not in pending:
                    continue
                try:
                    self._decide(
                        row_id,
                        user_id,
                        value if decision == 'post' else None,
                        skip=decision in {'skip', 'defer'},
                        transfer_account_id=value,
                        as_transfer=decision == 'transfer',
                        finalize=False,
                    )
                except (StatementMarkupConflictError, ValidationError):
                    continue
                decided += 1
            if decided:
                self._finalize(upload)
        return decided, len(decisions) - decided

    def post_transfer(
        self,
        row_id: int,
        user_id: int,
        account_id: int | None,
    ) -> BankStatementRow:
        """Close the row with a transfer to or from an own account."""
        with audit_operation(kind=AuditOperationKind.STATEMENT_MARKUP):
            return self._decide(
                row_id,
                user_id,
                None,
                skip=False,
                transfer_account_id=account_id,
                as_transfer=True,
            )

    def skip(self, row_id: int, user_id: int) -> BankStatementRow:
        """Defer the row without touching the balance (legacy name)."""
        with audit_operation(kind=AuditOperationKind.STATEMENT_MARKUP):
            return self._decide(row_id, user_id, None, skip=True)

    @transaction.atomic
    def _decide(
        self,
        row_id: int,
        user_id: int,
        category_id: int | None,
        *,
        skip: bool,
        transfer_account_id: int | None = None,
        as_transfer: bool = False,
        finalize: bool = True,
    ) -> BankStatementRow:
        if as_transfer:
            return self._decide_transfer(
                row_id,
                user_id,
                transfer_account_id,
                finalize=finalize,
            )
        upload, row = self._statement_row_repository.lock_owned_upload_and_row(
            row_id,
            user_id,
        )
        if skip and row.decision == BankStatementRow.Decision.DEFERRED:
            return row
        if row.decision != BankStatementRow.Decision.AWAITING_MARKUP:
            raise StatementMarkupConflictError(row.decision)
        if not row_has_bank_data(row):
            raise StatementMarkupConflictError('expired')

        if skip:
            self._statement_row_repository.suspend_row(
                row,
                BankStatementRow.Decision.DEFERRED,
                BankStatementRow.Decision.AWAITING_MARKUP,
                '',
                user_id,
            )
            self._coverage_service.invalidate_for_row_problem(
                row=row,
                reason='row_deferred',
            )
        else:
            self._post_transaction_decision(row, upload, category_id)
        if not skip:
            row.decided_at = timezone.now()
            row.save(
                update_fields=[
                    'transaction',
                    'transfer',
                    'decision',
                    'decided_at',
                ],
            )
            BankStatementDecisionAudit.objects.create(
                row=row,
                actor_id=user_id,
                decision=row.decision,
                transaction=row.transaction,
            )
        if finalize:
            self._finalize(upload)
        return row

    def _decide_transfer(
        self,
        row_id: int,
        user_id: int,
        account_id: int | None,
        *,
        finalize: bool,
    ) -> BankStatementRow:
        """Post an own transfer after locking both accounts in pk order.

        The counterparty pair is resolved read-only before any lock so the
        account locks follow the shared Accounts(sorted) -> upload -> row
        order. Values are then re-read under the locks; a changed number,
        account owner or row representation fails closed.
        """
        context = self._statement_row_repository.get_owned_row_context(
            row_id,
            user_id,
        )
        if context is None:
            raise BankStatementRow.DoesNotExist
        self._require_markup_row(context)
        counterparty, number_was_bound = self._counterparty_candidate(
            context,
            account_id,
        )
        account_ids = {context.upload.account_id, counterparty.pk}
        locked_accounts = self._account_repository.get_by_ids_for_update(
            account_ids,
        )
        if set(locked_accounts) != account_ids:
            raise StatementMarkupConflictError('account')

        upload, row = self._statement_row_repository.lock_owned_upload_and_row(
            row_id,
            user_id,
        )
        own = locked_accounts.get(upload.account_id)
        if own is None or own.user_id != user_id:
            raise StatementMarkupConflictError('account')
        if (
            row.kind != context.kind
            or row.counterparty_account != context.counterparty_account
            or upload.account_id != context.upload.account_id
        ):
            raise StatementMarkupConflictError('row')
        self._require_markup_row(row)
        if row.duplicate_of_id is not None:
            raise StatementMarkupConflictError('duplicate')

        other = self._counterparty_under_locks(
            row=row,
            upload=upload,
            account_id=account_id,
            expected_pk=counterparty.pk,
            number_was_bound=number_was_bound,
            locked_accounts=locked_accounts,
        )
        row.transfer = self._create_transfer(row, upload, own, other)
        row.decision = BankStatementRow.Decision.TRANSFERRED
        row.decided_at = timezone.now()
        row.save(
            update_fields=[
                'transaction',
                'transfer',
                'decision',
                'decided_at',
            ],
        )
        BankStatementDecisionAudit.objects.create(
            row=row,
            actor_id=user_id,
            decision=row.decision,
            transaction=row.transaction,
        )
        if finalize:
            self._finalize(upload)
        return row

    def _duplicate_root(
        self,
        row: BankStatementRow,
    ) -> BankStatementRow | None:
        """Return the original row of this duplicate representation, if any."""
        root = self._statement_row_repository.lock_duplicate_root(row)
        if row.duplicate_of_id is not None and root is None:
            raise StatementMarkupConflictError('duplicate')
        if root is not None and root.upload.account_id != row.upload.account_id:
            raise StatementMarkupConflictError('duplicate')
        return root

    def _post_transaction_decision(
        self,
        row: BankStatementRow,
        upload: BankStatementUpload,
        category_id: int | None,
    ) -> None:
        """Create the movement, or link a duplicate representation to it."""
        duplicate_root = self._duplicate_root(row)
        if duplicate_root is not None:
            if duplicate_root.transaction_id is None:
                raise StatementMarkupConflictError('duplicate')
            row.transaction = duplicate_root.transaction
            row.transfer = None
            row.decision = BankStatementRow.Decision.LINKED
            return
        row.transaction = self._create_movement(
            row,
            upload,
            category_id,
        )
        self._remember(row, upload.user, row.transaction)
        row.decision = BankStatementRow.Decision.NEW

    @transaction.atomic
    def _finalize(self, upload: BankStatementUpload) -> None:
        _account = Account.objects.select_for_update().get(pk=upload.account_id)
        locked = BankStatementUpload.objects.select_for_update().get(
            pk=upload.pk,
        )
        BankStatementReconciliationService.refresh_outcome_counts(locked)
        if self.pending_rows(locked).exists():
            return
        if (
            locked.retention_cleaned_at is not None
            or locked.expires_at <= timezone.now()
        ):
            # Cleanup removed the bank snapshot: never restore its sums.
            upload.statement_closing_balance = locked.statement_closing_balance
            upload.account_balance_after = locked.account_balance_after
            upload.balance_discrepancy = locked.balance_discrepancy
            return
        if self._balance_verification is None:
            # Without the verification service the closing balance is not
            # compared with the current balance: that would pretend the old
            # statement ends today. The check stays unverified.
            return
        self._balance_verification.verify(locked.pk, locked.user_id)

    def _create_movement(
        self,
        row: BankStatementRow,
        upload: BankStatementUpload,
        category_id: int | None,
    ) -> Transaction:
        transaction_type = row.transaction_type
        if (
            transaction_type is None
            or row.amount is None
            or row.transaction_date is None
        ):
            raise StatementMarkupConflictError('row')
        account = upload.account
        if account.is_archived or account.is_deposit:
            raise StatementMarkupConflictError('account')
        if (
            transaction_type == TransactionType.INCOME
            and account.type_account in constants.CREDIT_ACCOUNT_TYPES
        ):
            raise StatementMarkupConflictError(
                constants.CREDIT_CARD_INCOME_BAN,
            )
        category = self._category(row, upload.user, category_id)
        moment, bank_calendar_date = statement_row_movement_date(row)
        created = Transaction.objects.create(
            user=upload.user,
            account=account,
            category=category,
            type=transaction_type,
            amount=row.amount,
            date=moment,
            bank_calendar_date=bank_calendar_date,
            description=row.description,
            source_ref=None,
            source_ref_hash=row.source_ref_hash,
            source_ref_key_id=row.source_ref_key_id,
            source_ref_version=row.source_ref_version,
            source_identity_trusted=row.source_identity_trusted,
            source_file_hash=upload.file_hash or None,
            source_row_position=row.source_row_position,
        )
        delta = row.amount
        if transaction_type == TransactionType.EXPENSE:
            delta = -delta
        # The bank is the source of truth: no funds check.
        self._balance_service.apply_balance_delta(
            account,
            delta,
            check_funds=False,
        )
        note_financial_change(
            coverage_service=self._coverage_service,
            changes=[(account, bank_calendar_date or moment)],
        )
        return created

    @staticmethod
    def _remember(
        row: BankStatementRow,
        user: User,
        movement: Transaction,
    ) -> None:
        # A transfer to a person has no merchant key: nothing to remember.
        if not row.merchant_key or row.kind in _NO_MERCHANT_KINDS:
            return
        MerchantCategory.objects.update_or_create(
            user=user,
            merchant_key=row.merchant_key,
            transaction_type=movement.type,
            defaults={'category': movement.category},
        )

    def _create_transfer(
        self,
        row: BankStatementRow,
        upload: BankStatementUpload,
        own: Account,
        other: Account,
    ) -> TransferMoneyLog:
        if (
            row.kind
            not in {RosDorBankRowKind.OWN_C2C, RosDorBankRowKind.UNKNOWN}
            or row.transaction_type is None
            or row.amount is None
            or row.transaction_date is None
        ):
            raise StatementMarkupConflictError('row')
        if other.pk == own.pk:
            raise StatementMarkupConflictError('account')
        if own.is_deposit or other.is_deposit:
            raise StatementMarkupConflictError('account')
        if own.user_id != upload.user_id or other.user_id != upload.user_id:
            raise StatementMarkupConflictError('account')
        validate_same_currency(own, other)
        source, target = (
            (own, other)
            if row.transaction_type == TransactionType.EXPENSE
            else (other, own)
        )
        # The bank is the source of truth: no funds check.
        locked = self._balance_service.apply_account_deltas(
            {source.pk: -row.amount, target.pk: row.amount},
            check_funds=False,
        )
        moment, bank_calendar_date = statement_row_movement_date(row)
        transfer = self._transfer_log_repository.create_log(
            user=upload.user,
            from_account=locked[source.pk],
            to_account=locked[target.pk],
            amount=row.amount,
            exchange_date=moment,
            bank_calendar_date=bank_calendar_date,
            notes=row.description,
        )
        changed_at = bank_calendar_date or moment
        note_financial_change(
            coverage_service=self._coverage_service,
            changes=[
                (locked[source.pk], changed_at),
                (locked[target.pk], changed_at),
            ],
        )
        return transfer

    @staticmethod
    def _require_markup_row(row: BankStatementRow) -> None:
        """Fail closed unless the row may still be decided."""
        if row.decision != BankStatementRow.Decision.AWAITING_MARKUP:
            raise StatementMarkupConflictError(row.decision)
        if not row_has_bank_data(row):
            raise StatementMarkupConflictError('expired')

    def _counterparty_candidate(
        self,
        row: BankStatementRow,
        account_id: int | None,
    ) -> tuple[Account, bool]:
        """Resolve the counterparty pair read-only, before any lock."""
        number = (
            row.counterparty_account
            if row.kind == RosDorBankRowKind.OWN_C2C
            else ''
        )
        if number:
            found = self._account_repository.get_by_user_and_account_number(
                row.upload.user,
                number,
            )
            if found is not None:
                return found, True
        chosen = (
            Account.objects.filter(
                pk=account_id,
                user_id=row.upload.user_id,
            ).first()
            if account_id is not None
            else None
        )
        if chosen is None:
            raise StatementMarkupConflictError('account')
        return chosen, False

    def _counterparty_under_locks(
        self,
        *,
        row: BankStatementRow,
        upload: BankStatementUpload,
        account_id: int | None,
        expected_pk: int,
        number_was_bound: bool,
        locked_accounts: dict[int, Account],
    ) -> Account:
        """Re-read the counterparty after both accounts are locked.

        A number bound to another account is a changed counterparty and
        fails closed. An unbound number is attached to the chosen account
        only now, under its lock, so no write happens before the shared
        account lock order is established.
        """
        number = (
            row.counterparty_account
            if row.kind == RosDorBankRowKind.OWN_C2C
            else ''
        )
        if number:
            found = self._account_repository.get_by_user_and_account_number(
                upload.user,
                number,
            )
            if number_was_bound:
                if found is None or found.pk != expected_pk:
                    raise StatementMarkupConflictError('account')
            elif found is not None and found.pk != expected_pk:
                raise StatementMarkupConflictError('account')
            other = locked_accounts.get(expected_pk)
            if other is None:
                raise StatementMarkupConflictError('account')
            if found is None:
                if other.account_number:
                    raise StatementMarkupConflictError('account_number')
                other.account_number = number
                try:
                    with transaction.atomic():
                        other.save(update_fields=['account_number'])
                except IntegrityError as error:
                    raise StatementMarkupConflictError(
                        'account_number',
                    ) from error
        else:
            other = locked_accounts.get(expected_pk)
        if other is None or other.user_id != upload.user_id:
            raise StatementMarkupConflictError('account')
        return other

    @staticmethod
    def _category(
        row: BankStatementRow,
        user: User,
        category_id: int | None,
    ) -> Category:
        if category_id is not None:
            category = Category.objects.filter(
                pk=category_id,
                user=user,
                type=row.transaction_type,
                system_kind='',
            ).first()
            if category is None:
                raise StatementMarkupConflictError('category')
            return category
        if row.kind == RosDorBankRowKind.CANCEL:
            return Category.objects.get_or_create(
                user=user,
                name=REFUND_CATEGORY_NAME,
                type=row.transaction_type,
            )[0]
        raise StatementMarkupConflictError('category')
