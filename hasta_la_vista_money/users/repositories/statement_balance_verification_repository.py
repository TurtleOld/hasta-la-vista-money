"""ORM queries for historical bank balance verification."""

from collections.abc import Collection
from datetime import date

from django.db.models import Q, QuerySet

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import (
    UNRESOLVED_STATEMENT_DECISIONS,
    BankStatementRow,
    BankStatementUpload,
)


class StatementBalanceVerificationRepository:
    """Owner-scoped access to uploads and rows used by balance checks."""

    @staticmethod
    def owned_upload(
        upload_id: int,
        user_id: int,
    ) -> BankStatementUpload | None:
        """Return the upload when the user owns its account."""
        return (
            BankStatementUpload.objects.filter(
                pk=upload_id,
                user_id=user_id,
                account__user_id=user_id,
            )
            .select_related('account')
            .first()
        )

    @staticmethod
    def lock_owned_upload(
        upload_id: int,
        user_id: int,
    ) -> tuple[BankStatementUpload, Account]:
        """Lock account then upload in the agreed order.

        The account is resolved without a lock first so the ``FOR UPDATE``
        query locks a plain row. A foreign upload is not visible.
        """
        account_id = (
            BankStatementUpload.objects.filter(
                pk=upload_id,
                user_id=user_id,
                account__user_id=user_id,
            )
            .values_list('account_id', flat=True)
            .first()
        )
        if account_id is None:
            raise BankStatementUpload.DoesNotExist
        account = Account.objects.select_for_update().get(pk=account_id)
        upload = BankStatementUpload.objects.select_for_update().get(
            pk=upload_id,
            user_id=user_id,
        )
        upload.account = account
        return upload, account

    @staticmethod
    def unresolved_rows(account_id: int) -> QuerySet[BankStatementRow]:
        """Return unresolved rows of the account from any upload."""
        return BankStatementRow.objects.filter(
            upload__account_id=account_id,
            decision__in=UNRESOLVED_STATEMENT_DECISIONS,
        ).only(
            'transaction_date',
            'bank_calendar_date',
            'date_precision',
        )

    @staticmethod
    def blocking_uploads(
        user_id: int,
        account_ids: Collection[int] | None = None,
        period_start: date | None = None,
        period_end: date | None = None,
    ) -> QuerySet[BankStatementUpload]:
        """Return uploads whose retained mismatch still blocks finality.

        An upload without a known period is included in every requested
        period: an unscopable mismatch is not silently dropped.
        """
        uploads = BankStatementUpload.objects.filter(
            user_id=user_id,
            account__user_id=user_id,
            balance_unexplained_mismatch=True,
        )
        if account_ids is not None:
            uploads = uploads.filter(account_id__in=account_ids)
        if period_start is not None:
            uploads = uploads.filter(
                Q(statement_period_end__isnull=True)
                | Q(statement_period_end__gte=period_start),
            )
        if period_end is not None:
            uploads = uploads.filter(
                Q(statement_period_start__isnull=True)
                | Q(statement_period_start__lte=period_end),
            )
        return uploads.order_by('pk')

    @staticmethod
    def verifiable_uploads(
        account_ids: Collection[int],
    ) -> QuerySet[BankStatementUpload]:
        """Return uploads that carry a last result to invalidate."""
        return BankStatementUpload.objects.filter(
            account_id__in=account_ids,
            balance_verified_at__isnull=False,
            balance_needs_recheck=False,
        )
