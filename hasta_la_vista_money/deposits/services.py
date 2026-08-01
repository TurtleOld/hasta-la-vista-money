from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money.deposits.commands import (
    CreateDepositCommand,
    FundDepositCommand,
    OpenExistingDepositCommand,
)
from hasta_la_vista_money.deposits.models import (
    Deposit,
    DepositPrincipalEvent,
)
from hasta_la_vista_money.deposits.repositories import DepositRepository
from hasta_la_vista_money.finance_account.repositories import AccountRepository
from hasta_la_vista_money.finance_account.services.balance_service import (
    BalanceService,
)
from hasta_la_vista_money.users.models import User


class DepositService:
    def __init__(
        self,
        deposit_repository: DepositRepository,
        account_repository: AccountRepository,
    ) -> None:
        self.deposit_repository = deposit_repository
        self.account_repository = account_repository
        self.balance_service = BalanceService()

    @transaction.atomic
    def open_existing_term_deposit(
        self,
        command: OpenExistingDepositCommand,
    ) -> Deposit:
        """Record an already-active term deposit via a neutral opening position.

        Creates the deposit agreement with its current balance and records
        an immutable opening-position event. No monetary delta is applied —
        no income, expense, or transfer is created.

        Args:
            command: Details of the existing deposit, including current
                balance and tracking start date.

        Returns:
            The created Deposit.

        Raises:
            ValidationError: If agreement parameters are invalid or
                tracking_started_on is before opened_on.
        """
        self._validate_agreement(
            opened_on=command.opened_on,
            matures_on=command.matures_on,
            annual_rate=command.annual_rate,
            balance=command.current_balance,
        )
        if command.tracking_started_on < command.opened_on:
            raise ValidationError(
                _(
                    'Дата начала учёта не может быть раньше даты '
                    'открытия вклада.',
                ),
            )
        deposit = self._create_agreement(
            command=command,
            balance=command.current_balance,
        )
        self.deposit_repository.create_principal_event(
            deposit=deposit,
            type=DepositPrincipalEvent.Type.OPENING_POSITION,
            amount=command.current_balance,
            effective_on=command.tracking_started_on,
            source_account=None,
        )
        return deposit

    @transaction.atomic
    def create_funded_term_deposit(
        self,
        command: FundDepositCommand,
    ) -> Deposit:
        """Fund a new term deposit by transferring from an owned source account.

        Atomically decreases the source account balance and increases the
        deposit account balance, preserving total assets in the currency.
        Records an immutable funding event.

        Args:
            command: Funding details including source account, amount,
                and agreement parameters.

        Returns:
            The created Deposit.

        Raises:
            ValidationError: If the source account is invalid, in a different
                currency, has insufficient funds, or the amount is not positive.
        """
        self._validate_agreement(
            opened_on=command.opened_on,
            matures_on=command.matures_on,
            annual_rate=command.annual_rate,
            balance=command.amount,
        )
        if command.amount <= 0:
            raise ValidationError(
                _('Сумма финансирования должна быть больше нуля.'),
            )
        source_account = self.account_repository.get_by_id_and_user(
            command.source_account_id,
            command.user,
        )
        if source_account is None:
            raise ValidationError(_('Исходный счёт не найден или недоступен.'))
        if source_account.currency != command.currency:
            raise ValidationError(
                _('Исходный счёт должен быть в валюте вклада.'),
            )

        deposit = self._create_agreement(
            command=command,
            balance=Decimal(),
        )
        locked_accounts = self.balance_service.apply_account_deltas(
            {
                source_account.pk: -command.amount,
                deposit.account.pk: command.amount,
            },
        )
        self.deposit_repository.create_principal_event(
            deposit=deposit,
            type=DepositPrincipalEvent.Type.FUNDING,
            amount=command.amount,
            effective_on=command.opened_on,
            source_account=locked_accounts[source_account.pk],
        )
        return deposit

    @transaction.atomic
    def create_term_deposit(self, command: CreateDepositCommand) -> Deposit:
        self._validate_agreement(
            opened_on=command.opened_on,
            matures_on=command.matures_on,
            annual_rate=command.annual_rate,
            balance=command.balance,
        )
        deposit = self._create_agreement(
            command=command,
            balance=command.balance,
        )
        self.deposit_repository.create_principal_event(
            deposit=deposit,
            type=DepositPrincipalEvent.Type.OPENING_POSITION,
            amount=command.balance,
            effective_on=command.opened_on,
            source_account=None,
        )
        return deposit

    def _validate_agreement(
        self,
        *,
        opened_on: date,
        matures_on: date,
        annual_rate: Decimal,
        balance: Decimal,
    ) -> None:
        """Validate common deposit agreement parameters.

        Args:
            opened_on: Date the deposit was opened.
            matures_on: Date the deposit matures.
            annual_rate: Annual interest rate (must be positive).
            balance: Initial balance (must be non-negative).

        Raises:
            ValidationError: If any parameter is invalid.
        """
        if matures_on < opened_on:
            raise ValidationError(
                _('Дата окончания вклада не может быть раньше даты открытия.'),
            )
        if annual_rate <= 0:
            raise ValidationError(_('Годовая ставка должна быть больше нуля.'))
        if balance < 0:
            raise ValidationError(
                _('Остаток вклада не может быть отрицательным.'),
            )

    def _create_agreement(
        self,
        *,
        command: (
            CreateDepositCommand
            | FundDepositCommand
            | OpenExistingDepositCommand
        ),
        balance: Decimal,
    ) -> Deposit:
        """Create the deposit agreement: account, term, and rate period.

        Args:
            command: Deposit command carrying user, name, bank, currency,
                dates, and rate.
            balance: Starting balance for the deposit account.

        Returns:
            The persisted Deposit with associated account, term, and rate.
        """
        account = self.account_repository.create_deposit_account(
            user=command.user,
            name_account=command.name,
            bank=command.bank,
            currency=command.currency,
            balance=balance,
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
