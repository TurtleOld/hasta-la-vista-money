from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Final

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.translation import gettext as _

from hasta_la_vista_money import constants
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

REFUND_CATEGORY_NAME: Final = 'Возвраты'
_NO_MERCHANT_KINDS: Final = frozenset(
    {RosDorBankRowKind.C2C, RosDorBankRowKind.OWN_C2C},
)


class StatementMarkupConflictError(ValueError):
    """Raised when a row cannot be marked up as requested."""


class StatementMarkupService:
    """Post or skip RosDorBank statement rows after user markup."""

    def __init__(
        self,
        balance_service: BalanceService,
        account_repository: AccountRepository,
        transfer_log_repository: TransferMoneyLogRepository,
    ) -> None:
        self._balance_service = balance_service
        self._account_repository = account_repository
        self._transfer_log_repository = transfer_log_repository

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
            upload__user_id=user_id,
            upload__expires_at__gt=timezone.now(),
            upload__retention_cleaned_at__isnull=True,
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
            (row, local_row_date(row.transaction_date))
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
                local_row_date(movement.date),
                timedelta(0),
                str(movement.category.name),
            )
            for movement in Transaction.objects.without_adjustments()
            .filter(
                account_id=account_id,
                source_ref__isnull=True,
                date__date__range=(start, end),
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
                local_row_date(transfer.exchange_date),
                TRANSFER_DATE_WINDOW,
                _('Перевод: {source} → {target}')
                .format(
                    source=getattr(transfer.from_account, 'name_account', ''),
                    target=getattr(transfer.to_account, 'name_account', ''),
                )
                .strip(' →'),
            )
            for transfer in TransferMoneyLog.objects.filter(
                Q(from_account_id=account_id) | Q(to_account_id=account_id),
                user_id=upload.user_id,
                exchange_date__date__range=(start, end),
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
        or ``('skip', None)``. Returns the decided and the failed row counts.
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
                        skip=decision == 'skip',
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
        """Skip the row without touching the balance."""
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
        upload = (
            BankStatementUpload.objects.select_for_update()
            .select_related('account')
            .get(statement_rows__pk=row_id, user_id=user_id)
        )
        row = BankStatementRow.objects.select_for_update().get(
            pk=row_id,
            upload=upload,
        )
        if row.decision != BankStatementRow.Decision.AWAITING_MARKUP:
            raise StatementMarkupConflictError(row.decision)
        if timezone.now() >= upload.expires_at:
            raise StatementMarkupConflictError('expired')

        if skip:
            row.decision = BankStatementRow.Decision.SKIPPED
        elif as_transfer:
            row.transfer = self._create_transfer(
                row,
                upload,
                transfer_account_id,
            )
            row.decision = BankStatementRow.Decision.TRANSFERRED
        else:
            row.transaction = self._create_movement(
                row,
                upload,
                category_id,
            )
            self._remember(row, upload.user, row.transaction)
            row.decision = BankStatementRow.Decision.NEW
        row.decided_at = timezone.now()
        row.save(
            update_fields=['transaction', 'transfer', 'decision', 'decided_at'],
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

    def _finalize(self, upload: BankStatementUpload) -> None:
        BankStatementReconciliationService.refresh_outcome_counts(upload)
        if self.pending_rows(upload).exists():
            return
        upload.status = BankStatementUpload.Status.COMPLETED
        fields = ['status']
        closing = upload.statement_closing_balance
        if closing is not None:
            upload.account.refresh_from_db(fields=['balance'])
            upload.account_balance_after = upload.account.balance
            upload.balance_discrepancy = closing - upload.account.balance
            fields += ['account_balance_after', 'balance_discrepancy']
        upload.save(update_fields=fields)

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
        transaction_date = row.transaction_date
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
        moment = self._moment(transaction_date)
        created = Transaction.objects.create(
            user=upload.user,
            account=account,
            category=category,
            type=transaction_type,
            amount=row.amount,
            date=moment,
            description=row.description,
            source_ref=row.source_ref,
            source_file_hash=(upload.file_hash if not row.source_ref else None),
            source_row_position=(
                row.source_row_position if not row.source_ref else None
            ),
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

    @staticmethod
    def _moment(statement_date: datetime) -> datetime:
        # The statement has no time of day: use the moment of markup.
        now = timezone.localtime()
        return datetime.combine(
            timezone.localtime(statement_date).date(),
            now.time(),
            tzinfo=now.tzinfo,
        )

    def _create_transfer(
        self,
        row: BankStatementRow,
        upload: BankStatementUpload,
        account_id: int | None,
    ) -> TransferMoneyLog:
        if (
            row.kind
            not in {RosDorBankRowKind.OWN_C2C, RosDorBankRowKind.UNKNOWN}
            or row.transaction_type is None
            or row.amount is None
            or row.transaction_date is None
        ):
            raise StatementMarkupConflictError('row')
        own = upload.account
        other = self._counterparty(row, upload, account_id)
        if other.pk == own.pk:
            raise StatementMarkupConflictError('account')
        if own.is_deposit or other.is_deposit:
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
        return self._transfer_log_repository.create_log(
            user=upload.user,
            from_account=locked[source.pk],
            to_account=locked[target.pk],
            amount=row.amount,
            exchange_date=self._moment(row.transaction_date),
            notes=row.description,
        )

    def _counterparty(
        self,
        row: BankStatementRow,
        upload: BankStatementUpload,
        account_id: int | None,
    ) -> Account:
        """Own account of the transfer: by number, else the chosen one."""
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
            if found is not None:
                return found
        chosen = (
            Account.objects.filter(
                pk=account_id,
                user_id=upload.user_id,
            ).first()
            if account_id is not None
            else None
        )
        if chosen is None:
            raise StatementMarkupConflictError('account')
        if number:
            if chosen.account_number:
                raise StatementMarkupConflictError('account_number')
            chosen.account_number = number
            try:
                # The unique index rejects a number another account holds.
                with transaction.atomic():
                    chosen.save(update_fields=['account_number'])
            except IntegrityError as error:
                raise StatementMarkupConflictError('account_number') from error
        return chosen

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
