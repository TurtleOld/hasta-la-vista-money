from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money.deposits.commands import CreateDepositCommand
from hasta_la_vista_money.deposits.models import Deposit
from hasta_la_vista_money.deposits.repositories import DepositRepository
from hasta_la_vista_money.finance_account.repositories import AccountRepository
from hasta_la_vista_money.users.models import User


class DepositService:
    def __init__(
        self,
        deposit_repository: DepositRepository,
        account_repository: AccountRepository,
    ) -> None:
        self.deposit_repository = deposit_repository
        self.account_repository = account_repository

    @transaction.atomic
    def create_term_deposit(self, command: CreateDepositCommand) -> Deposit:
        if command.matures_on < command.opened_on:
            raise ValidationError(
                _('Дата окончания вклада не может быть раньше даты открытия.'),
            )
        if command.annual_rate <= 0:
            raise ValidationError(_('Годовая ставка должна быть больше нуля.'))
        if command.balance < 0:
            raise ValidationError(
                _('Остаток вклада не может быть отрицательным.'),
            )

        account = self.account_repository.create_deposit_account(
            user=command.user,
            name_account=command.name,
            bank=command.bank,
            currency=command.currency,
            balance=command.balance,
        )
        deposit = self.deposit_repository.create_deposit(
            account=account,
            name=command.name,
            bank=command.bank,
        )
        term = self.deposit_repository.create_term(
            deposit=deposit,
            opened_on=command.opened_on,
            matures_on=command.matures_on,
            is_current=True,
        )
        self.deposit_repository.create_rate_period(
            term=term,
            starts_on=command.opened_on,
            ends_on=command.matures_on,
            annual_rate=command.annual_rate,
        )
        return deposit

    def get_user_deposits(self, user: User) -> QuerySet[Deposit]:
        return self.deposit_repository.get_by_user(user)

    def get_user_deposit(self, deposit_id: int, user: User) -> Deposit:
        return self.deposit_repository.get_by_id_and_user(deposit_id, user)
