from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional, Protocol, runtime_checkable

from django.db.models import QuerySet

from hasta_la_vista_money import constants
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.models import (
        Account,
        TransferMoneyLog,
    )
    from hasta_la_vista_money.finance_account.services import (
        GracePeriodInfoDict,
        PaymentScheduleItemDict,
        RaiffeisenbankScheduleDict,
    )


@runtime_checkable
class AccountServiceProtocol(Protocol):
    def get_user_accounts(self, user: User) -> list['Account']: ...

    def get_account_by_id(
        self, account_id: int, user: User
    ) -> Optional['Account']: ...

    def get_credit_card_debt(
        self,
        account: 'Account',
        start_date: Any | None = None,
        end_date: Any | None = None,
    ) -> Decimal | None: ...

    def calculate_grace_period_info(
        self,
        account: 'Account',
        purchase_month: Any,
    ) -> 'GracePeriodInfoDict': ...

    def calculate_raiffeisenbank_payment_schedule(
        self,
        account: 'Account',
        purchase_month: Any,
    ) -> 'RaiffeisenbankScheduleDict': ...

    def apply_receipt_spend(
        self, account: 'Account', amount: Decimal
    ) -> 'Account': ...

    def refund_to_account(self, account: 'Account', amount: Decimal) -> 'Account': ...

    def reconcile_account_balances(
        self,
        old_account: 'Account',
        new_account: 'Account',
        old_total_sum: Decimal,
        new_total_sum: Decimal,
    ) -> None: ...

    def get_transfer_money_log(
        self,
        user: User,
        limit: int = constants.TRANSFER_MONEY_LOG_LIMIT,
    ) -> Any: ...

    def get_accounts_for_user_or_group(
        self,
        user: User,
        group_id: str | None = None,
    ) -> QuerySet['Account']: ...

    def get_sum_all_accounts(self, accounts: Any) -> Decimal: ...
