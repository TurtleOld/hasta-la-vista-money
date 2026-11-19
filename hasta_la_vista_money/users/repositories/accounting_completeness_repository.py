"""ORM reads for the independent accounting completeness assessment."""

from collections.abc import Sequence

from django.db.models import QuerySet

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    User,
)


class AccountingCompletenessRepository:
    """Read-only account, upload and row queries for completeness."""

    def accounts_for_owner(
        self,
        owner: User,
        account_ids: Sequence[int] | None = None,
    ) -> QuerySet[Account]:
        queryset = Account.objects.filter(user=owner).order_by('pk')
        if account_ids:
            queryset = queryset.filter(pk__in=account_ids)
        return queryset

    def uploads_for_accounts(
        self,
        account_ids: Sequence[int],
    ) -> QuerySet[BankStatementUpload]:
        return (
            BankStatementUpload.objects.filter(account_id__in=account_ids)
            .select_related('account')
            .order_by('account_id', 'created_at', 'pk')
        )

    def rows_for_uploads(
        self,
        upload_ids: Sequence[int],
    ) -> QuerySet[BankStatementRow]:
        return (
            BankStatementRow.objects.filter(upload_id__in=upload_ids)
            .select_related('upload', 'upload__account')
            .order_by('upload_id', 'pk')
        )
