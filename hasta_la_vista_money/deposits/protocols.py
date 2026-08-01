from typing import Protocol

from django.db.models import QuerySet

from hasta_la_vista_money.deposits.commands import CreateDepositCommand
from hasta_la_vista_money.deposits.models import Deposit
from hasta_la_vista_money.users.models import User


class DepositServiceProtocol(Protocol):
    def create_term_deposit(
        self,
        command: CreateDepositCommand,
    ) -> Deposit: ...

    def get_user_deposits(self, user: User) -> QuerySet[Deposit]: ...

    def get_user_deposit(self, deposit_id: int, user: User) -> Deposit: ...
