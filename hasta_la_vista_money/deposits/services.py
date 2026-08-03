import contextlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.deposits.commands import (
    AddFloatingRatePeriodCommand,
    CapitalizeInterestCommand,
    ConvertAccountToDepositCommand,
    CreateDepositCommand,
    ForecastTerms,
    FundDepositCommand,
    OpenExistingDepositCommand,
    RecalculateInterestForecastCommand,
    TopUpDepositCommand,
    TopUpTerms,
    WithdrawalTerms,
    WithdrawDepositCommand,
)
from hasta_la_vista_money.deposits.interest_forecast import (
    PrincipalChange,
    ProductionCalendar,
    RateSegment,
    WeekendOnlyCalendar,
    build_forecast,
)
from hasta_la_vista_money.deposits.models import (
    Deposit,
    DepositCapitalizationEvent,
    DepositInterestForecast,
    DepositPrincipalEvent,
    DepositRatePeriod,
    DepositTerm,
)
from hasta_la_vista_money.deposits.repositories import DepositRepository
from hasta_la_vista_money.finance_account.models import Bank
from hasta_la_vista_money.finance_account.repositories import (
    AccountRepository,
    TransferMoneyLogRepository,
)
from hasta_la_vista_money.finance_account.services.balance_service import (
    BalanceService,
)
from hasta_la_vista_money.users.models import User


class DepositService:
    def __init__(
        self,
        deposit_repository: DepositRepository,
        account_repository: AccountRepository,
        transfer_money_log_repository: TransferMoneyLogRepository,
        calendar: ProductionCalendar | None = None,
    ) -> None:
        self.deposit_repository = deposit_repository
        self.account_repository = account_repository
        self.transfer_money_log_repository = transfer_money_log_repository
        self.calendar: ProductionCalendar = calendar or WeekendOnlyCalendar()
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
    def convert_account_to_deposit(
        self,
        command: ConvertAccountToDepositCommand,
    ) -> Deposit:
        """Convert an existing production account into a term deposit.

        The account keeps its PK, balance, currency, owner, and timestamps.
        Its type changes to Deposit, and a deposit agreement, current term,
        rate period, and a neutral opening-position event dated on the
        conversion date are created. No monetary delta is applied.

        Args:
            command: Account identifier, agreement parameters, and the
                conversion date.

        Returns:
            The created Deposit, wrapping the same account.

        Raises:
            ValidationError: If the account is not found, not owned by the
                user, already of Deposit type, already linked to a deposit,
                or the agreement parameters are invalid.
        """
        account = self.account_repository.get_by_id_and_user(
            command.account_id,
            command.user,
        )
        if account is None:
            raise ValidationError(_('Счёт не найден или недоступен.'))
        if account.type_account == constants.ACCOUNT_TYPE_DEPOSIT:
            raise ValidationError(
                _('Счёт уже имеет тип «Вклад».'),
            )
        if Deposit.objects.filter(account=account).exists():
            raise ValidationError(
                _('Счёт уже связан со вкладом.'),
            )
        self._validate_agreement(
            opened_on=command.opened_on,
            matures_on=command.matures_on,
            annual_rate=command.annual_rate,
            balance=account.balance,
        )

        account.type_account = constants.ACCOUNT_TYPE_DEPOSIT
        account.save(update_fields=['type_account', 'updated_at'])

        bank_instance = self._resolve_bank(command.bank)
        deposit = self.deposit_repository.create_deposit(
            account=account,
            name=command.name,
            bank=bank_instance,
        )
        term = self.deposit_repository.create_term(
            deposit=deposit,
            opened_on=command.opened_on,
            matures_on=command.matures_on,
            is_current=True,
            rate_kind=command.rate_kind,
            **self._forecast_term_kwargs(command.forecast_terms),
            **self._withdrawal_term_kwargs(command.withdrawal_terms),
            **self._top_up_term_kwargs(command.top_up_terms),
        )
        self.deposit_repository.create_rate_period(
            term=term,
            starts_on=command.opened_on,
            ends_on=command.matures_on,
            annual_rate=command.annual_rate,
        )
        self._create_custom_schedule_dates(term, command.forecast_terms)
        self.deposit_repository.create_principal_event(
            deposit=deposit,
            type=DepositPrincipalEvent.Type.OPENING_POSITION,
            amount=account.balance,
            effective_on=command.converted_on,
            source_account=None,
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

    def _resolve_bank(self, bank: 'Bank | str') -> Bank:
        """Resolve a bank code or instance to a Bank instance."""
        if isinstance(bank, Bank):
            return bank
        return Bank.objects.get(code=bank)

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
        bank_instance = self._resolve_bank(command.bank)
        account = self.account_repository.create_deposit_account(
            user=command.user,
            name_account=command.name,
            bank=bank_instance,
            currency=command.currency,
            balance=balance,
        )
        deposit = self.deposit_repository.create_deposit(
            account=account,
            name=command.name,
            bank=bank_instance,
        )
        term = self.deposit_repository.create_term(
            deposit=deposit,
            opened_on=command.opened_on,
            matures_on=command.matures_on,
            is_current=True,
            rate_kind=command.rate_kind,
            **self._forecast_term_kwargs(command.forecast_terms),
            **self._withdrawal_term_kwargs(command.withdrawal_terms),
            **self._top_up_term_kwargs(command.top_up_terms),
        )
        self.deposit_repository.create_rate_period(
            term=term,
            starts_on=command.opened_on,
            ends_on=command.matures_on,
            annual_rate=command.annual_rate,
        )
        self._create_custom_schedule_dates(term, command.forecast_terms)
        return deposit

    def _forecast_term_kwargs(
        self,
        forecast_terms: ForecastTerms,
    ) -> dict[str, object]:
        return {
            'day_count_convention': forecast_terms.day_count_convention,
            'accrual_start_included': forecast_terms.accrual_start_included,
            'accrual_end_included': forecast_terms.accrual_end_included,
            'payout_schedule_kind': forecast_terms.payout_schedule_kind,
            'business_day_convention': forecast_terms.business_day_convention,
        }

    def _withdrawal_term_kwargs(
        self,
        withdrawal_terms: WithdrawalTerms,
    ) -> dict[str, object]:
        return {
            'withdrawal_allowed': withdrawal_terms.withdrawal_allowed,
            'minimum_withdrawal_amount': (
                withdrawal_terms.minimum_withdrawal_amount
            ),
            'maximum_withdrawal_amount': (
                withdrawal_terms.maximum_withdrawal_amount
            ),
            'withdrawal_deadline': withdrawal_terms.withdrawal_deadline,
            'minimum_balance': withdrawal_terms.minimum_balance,
        }

    def _top_up_term_kwargs(
        self,
        top_up_terms: TopUpTerms,
    ) -> dict[str, object]:
        return {
            'top_up_allowed': top_up_terms.top_up_allowed,
            'minimum_top_up_amount': top_up_terms.minimum_top_up_amount,
            'maximum_top_up_amount': top_up_terms.maximum_top_up_amount,
            'top_up_deadline': top_up_terms.top_up_deadline,
            'maximum_balance': top_up_terms.maximum_balance,
        }

    def _create_custom_schedule_dates(
        self,
        term: DepositTerm,
        forecast_terms: ForecastTerms,
    ) -> None:
        if forecast_terms.payout_schedule_kind != (
            DepositTerm.PayoutScheduleKind.CUSTOM
        ):
            return
        for payout_on in forecast_terms.custom_payout_dates:
            self.deposit_repository.create_payout_schedule_date(
                term=term,
                payout_on=payout_on,
            )

    @transaction.atomic
    def add_floating_rate_period(
        self,
        command: AddFloatingRatePeriodCommand,
    ) -> DepositRatePeriod:
        """Append a new effective-rate period to a floating-rate term.

        The previous period's end date is trimmed to the day before the new
        period's start; earlier periods are never modified. The term's
        forecast is recalculated afterwards (replacing only unconfirmed
        rows) so it reflects the new rate; if the term's payout schedule
        is misconfigured (e.g. custom without dates), the rate change
        still succeeds and the forecast is simply left stale.

        Args:
            command: Term identifier, new period's start date, rate, and a
                free-text note on the reason for the change.

        Returns:
            The newly created DepositRatePeriod.

        Raises:
            ValidationError: If the term is not found or not owned, is not
                floating-rate, has already matured, the rate is not
                positive, the note is blank, starts_on falls outside the
                term's bounds, or starts_on does not come after the last
                recorded period's start date.
        """
        try:
            term = self.deposit_repository.get_term_by_id_and_user(
                command.term_id,
                command.user,
            )
        except DepositTerm.DoesNotExist as error:
            raise ValidationError(
                _('Срок не найден или недоступен.'),
            ) from error

        if term.rate_kind != DepositTerm.RateKind.FLOATING:
            raise ValidationError(
                _(
                    'Добавлять периоды ставки можно только для '
                    'плавающей ставки.',
                ),
            )
        if term.state == DepositTerm.State.MATURED:
            raise ValidationError(
                _('Срок уже завершён, изменить ставку нельзя.'),
            )
        if command.annual_rate <= 0:
            raise ValidationError(_('Годовая ставка должна быть больше нуля.'))
        if not command.note.strip():
            raise ValidationError(
                _('Укажите пояснение к изменению ставки.'),
            )
        if not (term.opened_on <= command.starts_on <= term.matures_on):
            raise ValidationError(
                _('Дата начала периода должна попадать в срок вклада.'),
            )

        last_period = term.rate_periods.order_by('-starts_on').first()
        if (
            last_period is not None
            and command.starts_on <= last_period.starts_on
        ):
            raise ValidationError(
                _(
                    'Дата начала нового периода должна быть позже даты '
                    'начала последнего периода.',
                ),
            )

        if last_period is not None:
            self.deposit_repository.trim_rate_period_end(
                last_period.pk,
                command.starts_on - timedelta(days=1),
            )

        new_period = self.deposit_repository.create_rate_period(
            term=term,
            starts_on=command.starts_on,
            ends_on=term.matures_on,
            annual_rate=command.annual_rate,
            note=command.note.strip(),
        )
        with contextlib.suppress(ValidationError):
            self._recalculate_forecast_for_term(term)
        return new_period

    def get_user_deposits(self, user: User) -> QuerySet[Deposit]:
        return self.deposit_repository.get_by_user(user)

    def get_user_deposit(self, deposit_id: int, user: User) -> Deposit:
        return self.deposit_repository.get_by_id_and_user(deposit_id, user)

    @transaction.atomic
    def withdraw_deposit_principal(
        self,
        command: WithdrawDepositCommand,
    ) -> DepositPrincipalEvent:
        try:
            deposit = self.deposit_repository.get_by_id_and_user(
                command.deposit_id,
                command.user,
            )
        except Deposit.DoesNotExist as error:
            raise ValidationError(
                _('Вклад не найден или недоступен.'),
            ) from error
        destination = self.account_repository.get_by_id_and_user(
            command.destination_account_id,
            command.user,
        )
        if destination is None:
            raise ValidationError(
                _('Счёт назначения не найден или недоступен.'),
            )
        if destination.is_deposit:
            raise ValidationError(
                _('Средства можно вывести только на обычный счёт.'),
            )
        if destination.currency != deposit.account.currency:
            raise ValidationError(
                _('Счёт назначения должен быть в валюте вклада.'),
            )
        if command.amount <= 0:
            raise ValidationError(_('Сумма снятия должна быть больше нуля.'))
        term = deposit.current_term
        if not command.exception_reason.strip():
            self._validate_withdrawal_terms(
                term,
                command.amount,
                command.effective_on,
            )
        locked_accounts = self.balance_service.apply_account_deltas(
            {
                deposit.account.pk: -command.amount,
                destination.pk: command.amount,
            },
        )
        source = locked_accounts[deposit.account.pk]
        if source.balance < term.minimum_balance:
            raise ValidationError(
                _('Снятие нарушает неснижаемый остаток вклада.'),
            )
        event = self.deposit_repository.create_principal_event(
            deposit=deposit,
            type=DepositPrincipalEvent.Type.WITHDRAWAL,
            amount=command.amount,
            effective_on=command.effective_on,
            source_account=None,
            destination_account=locked_accounts[destination.pk],
            exception_reason=command.exception_reason.strip(),
        )
        self.transfer_money_log_repository.create_log(
            user=command.user,
            from_account=source,
            to_account=locked_accounts[destination.pk],
            amount=command.amount,
            exchange_date=datetime.combine(
                command.effective_on,
                datetime.min.time(),
                tzinfo=UTC,
            ),
            notes=_('Частичное снятие тела вклада.'),
        )
        return event

    @transaction.atomic
    def top_up_deposit_principal(
        self,
        command: TopUpDepositCommand,
    ) -> DepositPrincipalEvent:
        try:
            deposit = self.deposit_repository.get_by_id_and_user(
                command.deposit_id,
                command.user,
            )
        except Deposit.DoesNotExist as error:
            raise ValidationError(
                _('Вклад не найден или недоступен.'),
            ) from error
        source = self.account_repository.get_by_id_and_user(
            command.source_account_id,
            command.user,
        )
        if source is None or source.is_deposit:
            raise ValidationError(_('Исходный счёт не найден или недоступен.'))
        if source.currency != deposit.account.currency:
            raise ValidationError(
                _('Исходный счёт должен быть в валюте вклада.'),
            )
        if command.amount <= 0:
            raise ValidationError(
                _('Сумма пополнения должна быть больше нуля.'),
            )
        term = deposit.current_term
        account_ids = {source.pk, deposit.account.pk}
        locked_accounts = self.account_repository.get_by_ids_for_update(
            account_ids,
        )
        if len(locked_accounts) != len(account_ids):
            raise ValidationError(_('Счёт не найден или недоступен.'))
        source = locked_accounts[source.pk]
        deposit_account = locked_accounts[deposit.account.pk]
        if not term.opened_on <= command.effective_on <= term.matures_on:
            raise ValidationError(
                _('Дата пополнения должна попадать в срок вклада.'),
            )
        exception_reason = command.exception_reason.strip()
        if not exception_reason:
            self._validate_top_up_terms(
                term,
                command.amount,
                command.effective_on,
                deposit_account.balance,
            )
        locked_accounts = self.balance_service.apply_account_deltas(
            {
                source.pk: -command.amount,
                deposit.account.pk: command.amount,
            },
        )
        event = self.deposit_repository.create_principal_event(
            deposit=deposit,
            type=DepositPrincipalEvent.Type.TOP_UP,
            amount=command.amount,
            effective_on=command.effective_on,
            source_account=locked_accounts[source.pk],
            exception_reason=exception_reason,
        )
        self._recalculate_forecast_for_term(term, command.effective_on)
        return event

    @transaction.atomic
    def capitalize_interest(
        self,
        command: CapitalizeInterestCommand,
    ) -> DepositCapitalizationEvent:
        try:
            deposit = self.deposit_repository.get_by_id_and_user(
                command.deposit_id,
                command.user,
            )
        except Deposit.DoesNotExist as error:
            raise ValidationError(
                _('Вклад не найден или недоступен.'),
            ) from error

        self._validate_capitalization_amounts(command)
        forecast = self._resolve_capitalization_forecast(
            deposit,
            command,
        )

        self.balance_service.apply_account_deltas(
            {deposit.account.pk: command.net},
        )
        event = self.deposit_repository.create_capitalization_event(
            deposit=deposit,
            forecast=forecast,
            gross=command.gross,
            withholding=command.withholding,
            net=command.net,
            posting_on=command.posting_on,
            value_on=command.value_on,
            reason=command.reason.strip(),
        )
        if forecast is not None:
            self.deposit_repository.confirm_forecast(forecast.pk)
        with contextlib.suppress(ValidationError):
            self._recalculate_forecast_for_term(
                deposit.current_term,
                command.value_on,
            )
        return event

    def _validate_capitalization_amounts(
        self,
        command: CapitalizeInterestCommand,
    ) -> None:
        if command.gross < 0:
            raise ValidationError(
                _('Валовый процентный доход не может быть отрицательным.'),
            )
        if command.withholding < 0:
            raise ValidationError(
                _('Удержание не может быть отрицательным.'),
            )
        if command.net < 0:
            raise ValidationError(
                _('Чистый доход не может быть отрицательным.'),
            )
        if command.net == 0:
            raise ValidationError(
                _('Чистый доход должен быть больше нуля.'),
            )
        expected_net = (command.gross - command.withholding).quantize(
            command.net,
        )
        if expected_net != command.net:
            raise ValidationError(
                _(
                    'Суммы не согласованы: чистый доход (%(net)s) '
                    'должен равняться валовому доходу (%(gross)s) '
                    'за вычетом удержания (%(withholding)s).',
                )
                % {
                    'net': command.net,
                    'gross': command.gross,
                    'withholding': command.withholding,
                },
            )

    def _resolve_capitalization_forecast(
        self,
        deposit: Deposit,
        command: CapitalizeInterestCommand,
    ) -> DepositInterestForecast | None:
        if command.forecast_id is None:
            if not command.reason.strip():
                raise ValidationError(
                    _('Для внеплановой капитализации укажите причину.'),
                )
            return None
        try:
            forecast = deposit.current_term.interest_forecasts.get(
                pk=command.forecast_id,
            )
        except DepositInterestForecast.DoesNotExist as error:
            raise ValidationError(
                _(
                    'Ожидаемая выплата не найдена или не принадлежит вкладу.',
                ),
            ) from error
        if forecast.confirmed:
            raise ValidationError(
                _('Эта ожидаемая выплата уже подтверждена.'),
            )
        return forecast

    def _validate_top_up_terms(
        self,
        term: DepositTerm,
        amount: Decimal,
        effective_on: date,
        balance: Decimal,
    ) -> None:
        if not term.top_up_allowed:
            raise ValidationError(
                _('Условия вклада не разрешают пополнение.'),
            )
        if term.top_up_deadline and effective_on > term.top_up_deadline:
            raise ValidationError(_('Срок разрешённого пополнения уже истёк.'))
        if (
            term.minimum_top_up_amount is not None
            and amount < term.minimum_top_up_amount
        ):
            raise ValidationError(_('Сумма меньше минимально разрешённой.'))
        if (
            term.maximum_top_up_amount is not None
            and amount > term.maximum_top_up_amount
        ):
            raise ValidationError(_('Сумма больше максимально разрешённой.'))
        if (
            term.maximum_balance is not None
            and balance + amount > term.maximum_balance
        ):
            raise ValidationError(
                _('Пополнение превысит максимальный остаток.'),
            )

    def _validate_withdrawal_terms(
        self,
        term: DepositTerm,
        amount: Decimal,
        effective_on: date,
    ) -> None:
        if not term.withdrawal_allowed:
            raise ValidationError(
                _('Условия вклада не разрешают частичное снятие.'),
            )
        if term.withdrawal_deadline and effective_on > term.withdrawal_deadline:
            raise ValidationError(_('Срок разрешённого снятия уже истёк.'))
        if (
            term.minimum_withdrawal_amount is not None
            and amount < term.minimum_withdrawal_amount
        ):
            raise ValidationError(_('Сумма меньше минимально разрешённой.'))
        if (
            term.maximum_withdrawal_amount is not None
            and amount > term.maximum_withdrawal_amount
        ):
            raise ValidationError(_('Сумма больше максимально разрешённой.'))

    @transaction.atomic
    def recalculate_forecast(
        self,
        command: RecalculateInterestForecastCommand,
    ) -> list[DepositInterestForecast]:
        """Rebuild a term's expected interest payout forecast.

        Purely projective — never changes Account.balance, actual income
        or expense, or KPIs. Only unconfirmed forecast rows are replaced;
        rows already confirmed by an actual payout are left untouched.

        Args:
            command: Term identifier to recalculate the forecast for.

        Returns:
            The newly created forecast lines, in chronological order.

        Raises:
            ValidationError: If the term is not found or not owned by the
                user, or the term's payout schedule is custom without any
                configured schedule dates.
        """
        try:
            term = self.deposit_repository.get_term_by_id_and_user(
                command.term_id,
                command.user,
            )
        except DepositTerm.DoesNotExist as error:
            raise ValidationError(
                _('Срок не найден или недоступен.'),
            ) from error
        return self._recalculate_forecast_for_term(term)

    def _recalculate_forecast_for_term(
        self,
        term: DepositTerm,
        effective_on: date | None = None,
    ) -> list[DepositInterestForecast]:
        """Rebuild a term's forecast; caller has already resolved `term`.

        Raises:
            ValidationError: If the term's payout schedule is custom
                without any configured schedule dates.
        """
        rate_segments = [
            RateSegment(
                starts_on=period.starts_on,
                ends_on=period.ends_on,
                annual_rate=period.annual_rate,
            )
            for period in term.rate_periods.all()
        ]
        custom_payout_dates = [
            scheduled.payout_on
            for scheduled in term.payout_schedule_dates.all()
        ]
        if (
            term.payout_schedule_kind == DepositTerm.PayoutScheduleKind.CUSTOM
            and not custom_payout_dates
        ):
            raise ValidationError(
                _(
                    'Для индивидуального расписания укажите хотя бы одну '
                    'дату выплаты.',
                ),
            )

        principal_changes: list[PrincipalChange] = [
            PrincipalChange(
                effective_on=event.effective_on,
                amount=(
                    -event.amount
                    if event.type == DepositPrincipalEvent.Type.WITHDRAWAL
                    else event.amount
                ),
            )
            for event in term.deposit.principal_events.all()
        ]
        capitalization_changes = [
            PrincipalChange(
                effective_on=ce.value_on,
                amount=ce.net,
            )
            for ce in term.deposit.capitalization_events.all()
        ]
        principal_changes.extend(capitalization_changes)
        principal_changes.sort(key=lambda pc: pc.effective_on)

        lines = build_forecast(
            opened_on=term.opened_on,
            matures_on=term.matures_on,
            principal=Decimal(),
            rate_segments=rate_segments,
            day_count_convention=DepositTerm.DayCountConvention(
                term.day_count_convention,
            ),
            accrual_start_included=term.accrual_start_included,
            accrual_end_included=term.accrual_end_included,
            payout_schedule_kind=DepositTerm.PayoutScheduleKind(
                term.payout_schedule_kind,
            ),
            custom_payout_dates=custom_payout_dates,
            business_day_convention=DepositTerm.BusinessDayConvention(
                term.business_day_convention,
            ),
            calendar=self.calendar,
            principal_changes=principal_changes,
        )
        if effective_on is None:
            self.deposit_repository.delete_unconfirmed_forecasts(term.pk)
        else:
            self.deposit_repository.delete_future_unconfirmed_forecasts(
                term.pk,
                effective_on,
            )
            confirmed_payout_dates = set(
                term.interest_forecasts.filter(
                    confirmed=True,
                    payout_on__gte=effective_on,
                ).values_list('payout_on', flat=True),
            )
            lines = [
                line
                for line in lines
                if (
                    line.payout_on >= effective_on
                    and line.payout_on not in confirmed_payout_dates
                )
            ]
        return self.deposit_repository.create_forecast_lines(term, lines)
