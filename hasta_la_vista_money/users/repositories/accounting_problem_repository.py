"""Owner-scoped reads for the unified accounting problem service."""

from collections.abc import Sequence

from django.db.models import QuerySet

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
)


class AccountingProblemRepository:
    """Read statement rows and uploads without ever widening the owner."""

    @staticmethod
    def owner_accounts(owner_id: int) -> QuerySet[Account]:
        return (
            Account.objects.filter(user_id=owner_id)
            .select_related('bank')
            .order_by('name_account', 'pk')
        )

    @staticmethod
    def owned_account_ids(
        owner_id: int,
        account_ids: Sequence[int],
    ) -> set[int]:
        if not account_ids:
            return set()
        return set(
            Account.objects.filter(
                user_id=owner_id,
                pk__in=account_ids,
            ).values_list('pk', flat=True),
        )

    @staticmethod
    def statement_rows(
        owner_id: int,
        *,
        account_ids: Sequence[int] = (),
        bank_code: str = '',
        currency: str = '',
    ) -> QuerySet[BankStatementRow]:
        rows = BankStatementRow.objects.filter(
            upload__user_id=owner_id,
            upload__account__user_id=owner_id,
        ).select_related('upload__account__bank')
        if account_ids:
            rows = rows.filter(upload__account_id__in=account_ids)
        if bank_code:
            rows = rows.filter(upload__account__bank__code=bank_code)
        if currency:
            rows = rows.filter(upload__account__currency=currency)
        return rows.order_by('upload_id', 'source_row_position', 'pk')

    @staticmethod
    def uploads(
        owner_id: int,
        *,
        account_ids: Sequence[int] = (),
        bank_code: str = '',
        currency: str = '',
    ) -> QuerySet[BankStatementUpload]:
        uploads = BankStatementUpload.objects.filter(
            user_id=owner_id,
            account__user_id=owner_id,
        ).select_related('account__bank')
        if account_ids:
            uploads = uploads.filter(account_id__in=account_ids)
        if bank_code:
            uploads = uploads.filter(account__bank__code=bank_code)
        if currency:
            uploads = uploads.filter(account__currency=currency)
        return uploads.order_by('-created_at', '-pk')
