from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional, Protocol

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


class AccountServiceProtocol(Protocol):
    @staticmethod
    def get_user_accounts(user: User) -> list['Account']: ...

    @staticmethod
    def get_account_by_id(
        account_id: int, user: User
    ) -> Optional['Account']: ...

    @staticmethod
    def get_credit_card_debt(
        account: 'Account',
        start_date: Any | None = None,
        end_date: Any | None = None,
    ) -> Decimal | None: ...

    @staticmethod
    def calculate_grace_period_info(
        account: 'Account',
        purchase_month: Any,
    ) -> 'GracePeriodInfoDict': ...

    @staticmethod
    def calculate_payment_schedule(
        account: 'Account',
        purchase_month: Any,
    ) -> 'PaymentScheduleItemDict': ...

    @staticmethod
    def calculate_raiffeisenbank_payment_schedule(
        account: 'Account',
        purchase_month: Any,
    ) -> 'RaiffeisenbankScheduleDict': ...

    @staticmethod
    def transfer_money(
        from_account: 'Account',
        to_account: 'Account',
        amount: Decimal,
        user: User,
        exchange_date: datetime | None = None,
        notes: str | None = None,
    ) -> 'TransferMoneyLog': ...

    @staticmethod
    def apply_receipt_spend(
        account: 'Account', amount: Decimal
    ) -> 'Account': ...

    @staticmethod
    def refund_to_account(account: 'Account', amount: Decimal) -> 'Account': ...

    @staticmethod
    def reconcile_account_balances(
        old_account: 'Account',
        new_account: 'Account',
        old_total_sum: Decimal,
        new_total_sum: Decimal,
    ) -> None: ...

    @staticmethod
    def get_transfer_money_log(
        user: User,
        limit: int = constants.TRANSFER_MONEY_LOG_LIMIT,
    ) -> Any: ...

    @staticmethod
    def get_accounts_for_user_or_group(
        user: User,
        group_id: str | None = None,
    ) -> QuerySet['Account']: ...

    @staticmethod
    def get_sum_all_accounts(accounts: Any) -> Decimal: ...
