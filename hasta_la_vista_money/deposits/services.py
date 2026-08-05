import contextlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.deposits.commands import (
    AddFloatingRatePeriodCommand,
    CapitalizeInterestCommand,
    CloseDepositEarlyCommand,
    CloseMaturedDepositCommand,
    CloseMaturedDepositResult,
    ConfirmInterestPaymentCommand,
    ConvertAccountToDepositCommand,
    CreateDepositCommand,
    EarlyClosureTerms,
    ForecastEarlyClosureCommand,
    ForecastEarlyClosureResult,
    ForecastTerms,
    FundDepositCommand,
    OpenExistingDepositCommand,
    RecalculateInterestForecastCommand,
    RenewDepositCommand,
    ReverseDepositEventCommand,
    TopUpDepositCommand,
    TopUpTerms,
    WithdrawalTerms,
    WithdrawDepositCommand,
)
from hasta_la_vista_money.deposits.interest_forecast import (
    EarlyClosureRecalculationScope,
    PrincipalChange,
    ProductionCalendar,
    RateSegment,
    WeekendOnlyCalendar,
    build_forecast,
    forecast_early_closure,
)
from hasta_la_vista_money.deposits.models import (
    Deposit,
    DepositAuditEvent,
    DepositCapitalizationEvent,
    DepositInterestForecast,
    DepositPrincipalEvent,
    DepositRatePeriod,
    DepositRenewalEvent,
    DepositTerm,
    InterestPayoutDestination,
)
from hasta_la_vista_money.deposits.repositories import DepositRepository
from hasta_la_vista_money.finance_account.models import Account, Bank
from hasta_la_vista_money.finance_account.repositories import (
    AccountRepository,
    TransferMoneyLogRepository,
)
from hasta_la_vista_money.finance_account.services.balance_service import (
    BalanceService,
)
from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.users.services.cache import (
    invalidate_user_detailed_statistics_cache,
)


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
            **self._early_closure_term_kwargs(command.early_closure_terms),
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
        self._create_audit(
            deposit=deposit,
            event_type=DepositAuditEvent.Type.CONVERSION,
            description=(
                _('Счёт «{name}» преобразован во вклад.').format(
                    name=account.name_account,
                )
            ),
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
            **self._early_closure_term_kwargs(command.early_closure_terms),
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
            'interest_payout_destination': (
                forecast_terms.interest_payout_destination
            ),
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

    def _early_closure_term_kwargs(
        self,
        terms: EarlyClosureTerms,
    ) -> dict[str, object]:
        return {
            'early_closure_annual_rate': terms.annual_rate,
            'early_closure_recalculation_scope': terms.recalculation_scope,
            'early_closure_withdrawn_amount': terms.withdrawn_amount,
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
    def renew_matured_deposit(
        self,
        command: RenewDepositCommand,
    ) -> DepositTerm:
        """Start a new term without moving the deposit's principal."""
        try:
            deposit = self.deposit_repository.get_by_id_and_user_for_update(
                command.deposit_id,
                command.user,
            )
        except Deposit.DoesNotExist as error:
            raise ValidationError(
                _('Вклад не найден или недоступен.'),
            ) from error

        current_term = deposit.current_term
        if not self.is_renewal_available(deposit):
            raise ValidationError(
                _(
                    'Пролонгация доступна только для завершившегося '
                    'вклада с ненулевым остатком.',
                ),
            )
        self._validate_agreement(
            opened_on=command.opened_on,
            matures_on=command.matures_on,
            annual_rate=command.annual_rate,
            balance=deposit.account.balance,
        )
        if command.opened_on <= current_term.matures_on:
            raise ValidationError(
                _('Новый срок должен начинаться после завершённого срока.'),
            )
        if self.deposit_repository.get_overlapping_terms(
            deposit.pk,
            command.opened_on,
            command.matures_on,
        ).exists():
            raise ValidationError(
                _('Новый срок не должен пересекаться с историей вклада.'),
            )
        self._validate_renewal_terms(command)

        self.deposit_repository.mark_term_not_current(current_term.pk)
        new_term = self.deposit_repository.create_term(
            deposit=deposit,
            opened_on=command.opened_on,
            matures_on=command.matures_on,
            is_current=True,
            rate_kind=command.rate_kind,
            **self._forecast_term_kwargs(command.forecast_terms),
            **self._withdrawal_term_kwargs(command.withdrawal_terms),
            **self._top_up_term_kwargs(command.top_up_terms),
            **self._early_closure_term_kwargs(command.early_closure_terms),
        )
        self.deposit_repository.create_rate_period(
            term=new_term,
            starts_on=command.opened_on,
            ends_on=command.matures_on,
            annual_rate=command.annual_rate,
        )
        self._create_custom_schedule_dates(new_term, command.forecast_terms)
        self._recalculate_forecast_for_term(new_term)
        self.deposit_repository.create_renewal_event(
            deposit=deposit,
            previous_term=current_term,
            renewed_term=new_term,
            effective_on=command.opened_on,
        )
        self._create_audit(
            deposit=deposit,
            event_type=DepositAuditEvent.Type.RENEWAL,
            description=(
                _(
                    'Пролонгация вклада: новый срок с {opened} до {matures}.',
                ).format(
                    opened=command.opened_on,
                    matures=command.matures_on,
                )
            ),
        )
        return new_term

    @staticmethod
    def is_renewal_available(deposit: Deposit) -> bool:
        return (
            deposit.current_term.state == DepositTerm.State.MATURED
            and deposit.account.balance > 0
            and not deposit.account.is_archived
        )

    @staticmethod
    def _validate_renewal_terms(command: RenewDepositCommand) -> None:
        for payout_on in command.forecast_terms.custom_payout_dates:
            if not command.opened_on <= payout_on <= command.matures_on:
                raise ValidationError(
                    _('Дата выплаты должна попадать в новый срок вклада.'),
                )
        for deadline in (
            command.withdrawal_terms.withdrawal_deadline,
            command.top_up_terms.top_up_deadline,
        ):
            if deadline is not None and not (
                command.opened_on <= deadline <= command.matures_on
            ):
                raise ValidationError(
                    _('Срок операции должен попадать в новый срок вклада.'),
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
        if term.state in (
            DepositTerm.State.MATURED,
            DepositTerm.State.CLOSED,
        ):
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
    def reverse_deposit_event(
        self,
        command: ReverseDepositEventCommand,
    ) -> (
        DepositPrincipalEvent | DepositCapitalizationEvent | DepositRenewalEvent
    ):
        reason = command.reason.strip()
        if not reason:
            raise ValidationError(_('Укажите причину аннулирования.'))
        if command.event_kind == 'interest':
            reversal_interest = self._reverse_interest_event(
                command,
                reason,
            )
            self._create_audit(
                deposit=reversal_interest.deposit,
                event_type=DepositAuditEvent.Type.CANCELLATION,
                description=(
                    _(
                        'Аннулирование выплаты процентов: {reason}.',
                    ).format(reason=reason)
                ),
            )
            return reversal_interest
        if command.event_kind == 'renewal':
            reversal_renewal = self._reverse_renewal_event(
                command,
                reason,
            )
            self._create_audit(
                deposit=reversal_renewal.deposit,
                event_type=DepositAuditEvent.Type.CANCELLATION,
                description=(
                    _(
                        'Аннулирование пролонгации: {reason}.',
                    ).format(reason=reason)
                ),
            )
            return reversal_renewal
        if command.event_kind != 'principal':
            raise ValidationError(_('Неизвестный тип события вклада.'))
        result = self._reverse_principal_event(command, reason)
        self._create_audit(
            deposit=result.deposit,
            event_type=DepositAuditEvent.Type.CANCELLATION,
            description=str(
                _(
                    'Аннулирование события «{type}»: {reason}.',
                ).format(
                    type=result.get_type_display(),
                    reason=reason,
                ),
            ),
        )
        return result

    def _reverse_principal_event(
        self,
        command: ReverseDepositEventCommand,
        reason: str,
    ) -> DepositPrincipalEvent:
        try:
            event = self.deposit_repository.get_principal_event_for_update(
                command.event_id,
                command.user,
            )
        except DepositPrincipalEvent.DoesNotExist as error:
            raise ValidationError(
                _('Событие вклада не найдено или недоступно.'),
            ) from error
        self._validate_reversal_deposit(event.deposit_id, command.deposit_id)
        self._validate_reversal_source(event)
        if command.reversed_on < event.effective_on:
            raise ValidationError(
                _('Дата аннулирования не может быть раньше даты события.'),
            )

        if event.type in (
            DepositPrincipalEvent.Type.PLANNED_CLOSURE,
            DepositPrincipalEvent.Type.EARLY_CLOSURE,
        ):
            return self._reverse_closure_event(command, event, reason)

        account_deltas: dict[int, Decimal] = {}
        if event.type in (
            DepositPrincipalEvent.Type.FUNDING,
            DepositPrincipalEvent.Type.TOP_UP,
        ):
            if event.source_account_id is None:
                raise ValidationError(_('Исходный счёт события не найден.'))
            account_deltas = {
                event.source_account_id: event.amount,
                event.deposit.account_id: -event.amount,
            }
        elif event.type == DepositPrincipalEvent.Type.WITHDRAWAL:
            if event.destination_account_id is None:
                raise ValidationError(_('Счёт назначения события не найден.'))
            account_deltas = {
                event.deposit.account_id: event.amount,
                event.destination_account_id: -event.amount,
            }
        if account_deltas:
            locked_accounts = self.balance_service.apply_account_deltas(
                account_deltas,
            )
            self._create_principal_reversal_log(
                command,
                event,
                locked_accounts,
            )

        reversal = self.deposit_repository.create_principal_event(
            deposit=event.deposit,
            type=event.type,
            amount=event.amount,
            effective_on=command.reversed_on,
            posting_on=command.reversed_on if event.posting_on else None,
            destination=event.destination,
            source_account=event.source_account,
            destination_account=event.destination_account,
            exception_reason='',
            reversal_of=event,
            reversal_reason=reason,
        )
        with contextlib.suppress(ValidationError):
            self._recalculate_forecast_for_term(
                event.deposit.current_term,
                command.reversed_on,
            )
        return reversal

    def _reverse_renewal_event(
        self,
        command: ReverseDepositEventCommand,
        reason: str,
    ) -> DepositRenewalEvent:
        try:
            event = self.deposit_repository.get_renewal_event_for_update(
                command.event_id,
                command.user,
            )
        except DepositRenewalEvent.DoesNotExist as error:
            raise ValidationError(
                _('Событие вклада не найдено или недоступно.'),
            ) from error
        self._validate_reversal_deposit(event.deposit_id, command.deposit_id)
        self._validate_reversal_source(event)
        if (
            event.previous_term.deposit_id != event.deposit_id
            or event.renewed_term.deposit_id != event.deposit_id
            or event.previous_term_id == event.renewed_term_id
        ):
            raise ValidationError(_('История пролонгации вклада повреждена.'))
        if command.reversed_on < event.effective_on:
            raise ValidationError(
                _('Дата аннулирования не может быть раньше даты события.'),
            )
        if not event.renewed_term.is_current:
            raise ValidationError(
                _('Сначала аннулируйте последующие события вклада.'),
            )
        self.deposit_repository.set_current_term(
            event.renewed_term_id,
            is_current=False,
        )
        self.deposit_repository.set_current_term(
            event.previous_term_id,
            is_current=True,
        )
        return self.deposit_repository.create_renewal_event(
            deposit=event.deposit,
            previous_term=event.previous_term,
            renewed_term=event.renewed_term,
            effective_on=command.reversed_on,
            reversal_of=event,
            reversal_reason=reason,
        )

    def _reverse_closure_event(
        self,
        command: ReverseDepositEventCommand,
        event: DepositPrincipalEvent,
        reason: str,
    ) -> DepositPrincipalEvent:
        try:
            interest_event = (
                self.deposit_repository.get_closure_interest_event_for_update(
                    event,
                )
            )
        except DepositCapitalizationEvent.DoesNotExist as error:
            raise ValidationError(
                _('Связанная финальная выплата не найдена.'),
            ) from error
        deposit = event.deposit
        term = deposit.current_term
        self.account_repository.unarchive(deposit.account_id)
        account_deltas = {deposit.account_id: event.amount}
        if event.destination_account_id is not None:
            account_deltas[event.destination_account_id] = -(
                event.amount + interest_event.net
            )
        self.balance_service.apply_account_deltas(account_deltas)
        principal_reversal = self.deposit_repository.create_principal_event(
            deposit=deposit,
            type=event.type,
            amount=event.amount,
            effective_on=command.reversed_on,
            posting_on=command.reversed_on,
            destination=event.destination,
            source_account=None,
            destination_account=event.destination_account,
            exception_reason='',
            reversal_of=event,
            reversal_reason=reason,
        )
        self.deposit_repository.create_capitalization_event(
            deposit=deposit,
            forecast=None,
            destination=interest_event.destination,
            destination_account=interest_event.destination_account,
            gross=interest_event.gross,
            withholding=interest_event.withholding,
            net=interest_event.net,
            posting_on=command.reversed_on,
            value_on=command.reversed_on,
            reason=interest_event.reason,
            is_final=True,
            prior_interest_adjustment=(
                interest_event.prior_interest_adjustment
            ),
            reversal_of=interest_event,
            reversal_reason=reason,
        )
        self.deposit_repository.reopen_term(term.pk)
        transaction.on_commit(
            lambda: invalidate_user_detailed_statistics_cache(command.user.pk),
        )
        return principal_reversal

    def _reverse_interest_event(
        self,
        command: ReverseDepositEventCommand,
        reason: str,
    ) -> DepositCapitalizationEvent:
        try:
            event = self.deposit_repository.get_interest_event_for_update(
                command.event_id,
                command.user,
            )
        except DepositCapitalizationEvent.DoesNotExist as error:
            raise ValidationError(
                _('Событие вклада не найдено или недоступно.'),
            ) from error
        self._validate_reversal_deposit(event.deposit_id, command.deposit_id)
        self._validate_reversal_source(event)
        if command.reversed_on < event.posting_on:
            raise ValidationError(
                _('Дата аннулирования не может быть раньше даты события.'),
            )

        account_id: int | None = None
        if event.destination == event.Destination.CAPITALIZATION:
            account_id = event.deposit.account_id
        elif event.destination_account_id is not None:
            account_id = event.destination_account_id
        if account_id is not None and event.net:
            self.balance_service.apply_account_deltas(
                {account_id: -event.net},
            )

        reversal = self.deposit_repository.create_capitalization_event(
            deposit=event.deposit,
            forecast=None,
            destination=event.destination,
            destination_account=event.destination_account,
            gross=event.gross,
            withholding=event.withholding,
            net=event.net,
            posting_on=command.reversed_on,
            value_on=command.reversed_on,
            reason=event.reason,
            is_final=event.is_final,
            prior_interest_adjustment=event.prior_interest_adjustment,
            reversal_of=event,
            reversal_reason=reason,
        )
        transaction.on_commit(
            lambda: invalidate_user_detailed_statistics_cache(command.user.pk),
        )
        return reversal

    @staticmethod
    def _validate_reversal_source(
        event: (
            DepositPrincipalEvent
            | DepositCapitalizationEvent
            | DepositRenewalEvent
        ),
    ) -> None:
        if event.reversal_of_id is not None:
            raise ValidationError(
                _('Компенсирующее событие нельзя аннулировать.'),
            )
        if hasattr(event, 'reversal'):
            raise ValidationError(_('Событие вклада уже аннулировано.'))

    @staticmethod
    def _validate_reversal_deposit(
        event_deposit_id: int,
        command_deposit_id: int,
    ) -> None:
        if event_deposit_id != command_deposit_id:
            raise ValidationError(
                _('Событие не принадлежит указанному вкладу.'),
            )

    def _create_principal_reversal_log(
        self,
        command: ReverseDepositEventCommand,
        event: DepositPrincipalEvent,
        accounts: dict[int, Account],
    ) -> None:
        from_account: Account | None = None
        to_account: Account | None = None
        if event.type in (
            DepositPrincipalEvent.Type.FUNDING,
            DepositPrincipalEvent.Type.TOP_UP,
        ):
            from_account = accounts[event.deposit.account_id]
            if event.source_account_id is not None:
                to_account = accounts[event.source_account_id]
        elif event.type == DepositPrincipalEvent.Type.WITHDRAWAL:
            if event.destination_account_id is not None:
                from_account = accounts[event.destination_account_id]
            to_account = accounts[event.deposit.account_id]
        if from_account is None or to_account is None:
            return
        self.transfer_money_log_repository.create_log(
            user=command.user,
            from_account=from_account,
            to_account=to_account,
            amount=event.amount,
            exchange_date=datetime.combine(
                command.reversed_on,
                datetime.min.time(),
                tzinfo=UTC,
            ),
            notes=_('Аннулирование события тела вклада.'),
        )

    @staticmethod
    def _signed_principal_amount(event: DepositPrincipalEvent) -> Decimal:
        is_outflow = event.type in (
            DepositPrincipalEvent.Type.WITHDRAWAL,
            DepositPrincipalEvent.Type.PLANNED_CLOSURE,
            DepositPrincipalEvent.Type.EARLY_CLOSURE,
        )
        amount = -event.amount if is_outflow else event.amount
        return -amount if event.reversal_of_id else amount

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
        if destination.is_archived:
            raise ValidationError(_('Счёт назначения находится в архиве.'))
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
        if term.state == DepositTerm.State.CLOSED:
            raise ValidationError(_('Закрытый вклад недоступен для операций.'))

        if command.external_id:
            existing = self._check_principal_idempotency(
                deposit_id=deposit.pk,
                external_id=command.external_id,
                event_type=DepositPrincipalEvent.Type.WITHDRAWAL,
                amount=command.amount,
                effective_on=command.effective_on,
            )
            if existing is not None:
                return existing

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
            external_id=command.external_id,
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
        if command.exception_reason.strip():
            self._create_audit(
                deposit=deposit,
                event_type=DepositAuditEvent.Type.EXCLUSION,
                description=command.exception_reason.strip(),
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
        if source is None or source.is_deposit or source.is_archived:
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
        if term.state == DepositTerm.State.CLOSED:
            raise ValidationError(_('Закрытый вклад недоступен для операций.'))

        if command.external_id:
            existing = self._check_principal_idempotency(
                deposit_id=deposit.pk,
                external_id=command.external_id,
                event_type=DepositPrincipalEvent.Type.TOP_UP,
                amount=command.amount,
                effective_on=command.effective_on,
            )
            if existing is not None:
                return existing

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
            external_id=command.external_id,
        )
        self._recalculate_forecast_for_term(term, command.effective_on)
        if exception_reason:
            self._create_audit(
                deposit=deposit,
                event_type=DepositAuditEvent.Type.EXCLUSION,
                description=exception_reason,
            )
        return event

    def capitalize_interest(
        self,
        command: CapitalizeInterestCommand,
    ) -> DepositCapitalizationEvent:
        return self.confirm_interest_payment(command)

    @transaction.atomic
    def confirm_interest_payment(
        self,
        command: ConfirmInterestPaymentCommand,
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

        if deposit.current_term.state == DepositTerm.State.CLOSED:
            raise ValidationError(_('Закрытый вклад недоступен для операций.'))

        if command.external_id:
            existing = self._check_capitalization_idempotency(
                deposit_id=deposit.pk,
                external_id=command.external_id,
                gross=command.gross,
                withholding=command.withholding,
                net=command.net,
                posting_on=command.posting_on,
                value_on=command.value_on,
            )
            if existing is not None:
                return existing

        self._validate_capitalization_amounts(command)
        forecast = self._resolve_capitalization_forecast(
            deposit,
            command,
        )
        destination_account = self._resolve_interest_destination(
            deposit,
            command,
        )
        account_deltas: dict[int, Decimal] = {}
        if (
            command.destination
            == DepositCapitalizationEvent.Destination.CAPITALIZATION
        ):
            account_deltas[deposit.account.pk] = command.net
        elif destination_account is not None:
            account_deltas[destination_account.pk] = command.net
        if account_deltas:
            self.balance_service.apply_account_deltas(account_deltas)
        event = self.deposit_repository.create_capitalization_event(
            deposit=deposit,
            forecast=forecast,
            gross=command.gross,
            withholding=command.withholding,
            net=command.net,
            posting_on=command.posting_on,
            value_on=command.value_on,
            reason=command.reason.strip(),
            destination=command.destination,
            destination_account=destination_account,
            external_id=command.external_id,
        )
        if forecast is not None:
            self.deposit_repository.confirm_forecast(forecast.pk)
        transaction.on_commit(
            lambda: invalidate_user_detailed_statistics_cache(command.user.pk),
        )
        self._create_audit(
            deposit=deposit,
            event_type=DepositAuditEvent.Type.CONFIRMATION,
            description=(
                _('Выплата процентов: {net} (нетто).').format(
                    net=command.net,
                )
            ),
        )
        if (
            command.destination
            == DepositCapitalizationEvent.Destination.CAPITALIZATION
        ):
            with contextlib.suppress(ValidationError):
                self._recalculate_forecast_for_term(
                    deposit.current_term,
                    command.value_on,
                )
        return event

    def forecast_early_closure(
        self,
        command: ForecastEarlyClosureCommand,
    ) -> ForecastEarlyClosureResult:
        try:
            deposit = self.deposit_repository.get_by_id_and_user(
                command.deposit_id,
                command.user,
            )
        except Deposit.DoesNotExist as error:
            raise ValidationError(
                _('Вклад не найден или недоступен.'),
            ) from error
        term = deposit.current_term
        if term.state != DepositTerm.State.ACTIVE:
            raise ValidationError(
                _('Досрочное закрытие доступно только для активного вклада.'),
            )
        if not term.opened_on <= command.closure_on < term.matures_on:
            raise ValidationError(
                _('Дата досрочного закрытия должна попадать в срок вклада.'),
            )
        scope = EarlyClosureRecalculationScope(
            term.early_closure_recalculation_scope,
        )
        if (
            scope == EarlyClosureRecalculationScope.UNSUPPORTED
            or term.early_closure_annual_rate is None
        ):
            return ForecastEarlyClosureResult(
                principal=deposit.account.balance,
                gross=None,
                recalculation_scope=scope,
                is_uncertain=True,
                uncertainty_reason=str(
                    _('Формула банка не поддерживается.'),
                ),
            )
        current_period_opened_on = term.opened_on
        previous_payment = self.deposit_repository.get_latest_interest_event(
            deposit.pk,
            command.closure_on,
        )
        if previous_payment is not None:
            current_period_opened_on = previous_payment.value_on
        forecast = forecast_early_closure(
            scope=scope,
            closure_on=command.closure_on,
            term_opened_on=term.opened_on,
            current_period_opened_on=current_period_opened_on,
            principal=deposit.account.balance,
            withdrawn_amount=(
                term.early_closure_withdrawn_amount or deposit.account.balance
            ),
            annual_rate=term.early_closure_annual_rate,
            day_count_convention=DepositTerm.DayCountConvention(
                term.day_count_convention,
            ),
            accrual_start_included=term.accrual_start_included,
            accrual_end_included=term.accrual_end_included,
        )
        return ForecastEarlyClosureResult(
            principal=deposit.account.balance,
            gross=forecast.gross,
            recalculation_scope=forecast.scope,
            is_uncertain=forecast.is_uncertain,
            uncertainty_reason=forecast.uncertainty_reason,
        )

    @transaction.atomic
    def close_deposit_early(
        self,
        command: CloseDepositEarlyCommand,
    ) -> CloseMaturedDepositResult:
        try:
            deposit = self.deposit_repository.get_by_id_and_user_for_update(
                command.deposit_id,
                command.user,
            )
        except Deposit.DoesNotExist as error:
            raise ValidationError(
                _('Вклад не найден или недоступен.'),
            ) from error
        term = deposit.current_term
        self._validate_early_closure(term, command)
        destination_account = self._resolve_closure_destination(
            deposit,
            command,
        )
        account_ids = {deposit.account.pk}
        if destination_account is not None:
            account_ids.add(destination_account.pk)
        closure_accounts = self.account_repository.get_by_ids_for_update(
            account_ids,
        )
        if len(closure_accounts) != len(account_ids):
            raise ValidationError(_('Счёт закрытия не найден или недоступен.'))
        deposit.account = closure_accounts[deposit.account.pk]
        if command.principal != deposit.account.balance:
            raise ValidationError(
                _('Возвращаемое тело должно совпадать с остатком вклада.'),
            )
        self._validate_closure_interest_amounts(command)
        self._validate_early_closure_adjustment(command)

        account_deltas = {deposit.account.pk: -command.principal}
        if destination_account is not None:
            destination_account = closure_accounts[destination_account.pk]
            account_deltas[destination_account.pk] = (
                command.principal + command.net
            )
        locked_accounts = self.balance_service.apply_account_deltas(
            account_deltas,
        )
        closed_account = locked_accounts.get(
            deposit.account.pk,
            closure_accounts[deposit.account.pk],
        )
        if closed_account.balance != 0:
            raise ValidationError(
                _('После закрытия остаток счёта вклада должен быть нулевым.'),
            )
        principal_event = self.deposit_repository.create_principal_event(
            deposit=deposit,
            type=DepositPrincipalEvent.Type.EARLY_CLOSURE,
            amount=command.principal,
            posting_on=command.posting_on,
            effective_on=command.value_on,
            source_account=None,
            destination=command.destination,
            destination_account=destination_account,
            exception_reason=command.closure_reason.strip(),
            external_id=command.external_id,
        )
        interest_event = self.deposit_repository.create_capitalization_event(
            deposit=deposit,
            forecast=None,
            gross=command.gross,
            withholding=command.withholding,
            net=command.net,
            prior_interest_adjustment=command.prior_interest_adjustment,
            posting_on=command.posting_on,
            value_on=command.value_on,
            reason=command.closure_reason.strip(),
            destination=command.destination,
            destination_account=destination_account,
            is_final=True,
            external_id=command.external_id,
        )
        self.deposit_repository.delete_unconfirmed_forecasts(term.pk)
        self.deposit_repository.close_term(term.pk, command.value_on)
        self.account_repository.archive(deposit.account.pk)
        transaction.on_commit(
            lambda: invalidate_user_detailed_statistics_cache(command.user.pk),
        )
        self._create_audit(
            deposit=deposit,
            event_type=DepositAuditEvent.Type.CLOSURE,
            description=(
                _(
                    'Досрочное закрытие вклада: {reason}.',
                ).format(reason=command.closure_reason.strip())
            ),
        )
        return CloseMaturedDepositResult(
            principal_event=principal_event,
            interest_event=interest_event,
        )

    @staticmethod
    def _validate_early_closure(
        term: DepositTerm,
        command: CloseDepositEarlyCommand,
    ) -> None:
        if term.state != DepositTerm.State.ACTIVE:
            raise ValidationError(
                _('Досрочное закрытие доступно только для активного вклада.'),
            )
        if not command.closure_reason.strip():
            raise ValidationError(_('Укажите причину досрочного закрытия.'))
        if not term.opened_on <= command.value_on < term.matures_on:
            raise ValidationError(
                _('Дата досрочного закрытия должна попадать в срок вклада.'),
            )
        if command.posting_on >= term.matures_on:
            raise ValidationError(
                _('Дата проводки должна быть раньше окончания срока.'),
            )

    @staticmethod
    def _validate_early_closure_adjustment(
        command: CloseDepositEarlyCommand,
    ) -> None:
        if command.prior_interest_adjustment != (
            command.prior_interest_adjustment.quantize(
                constants.MIN_MONEY_AMOUNT,
            )
        ):
            raise ValidationError(
                _('Корректировка должна иметь точность до копеек.'),
            )

    @transaction.atomic
    def close_matured_deposit(
        self,
        command: CloseMaturedDepositCommand,
    ) -> CloseMaturedDepositResult:
        try:
            deposit = self.deposit_repository.get_by_id_and_user_for_update(
                command.deposit_id,
                command.user,
            )
        except Deposit.DoesNotExist as error:
            raise ValidationError(
                _('Вклад не найден или недоступен.'),
            ) from error

        existing_result = self._existing_closure_result(deposit.pk, command)
        if existing_result is not None:
            return existing_result
        term = deposit.current_term
        destination_account = self._resolve_closure_destination(
            deposit,
            command,
        )
        account_ids = {deposit.account.pk}
        if destination_account is not None:
            account_ids.add(destination_account.pk)
        closure_accounts = self.account_repository.get_by_ids_for_update(
            account_ids,
        )
        if len(closure_accounts) != len(account_ids):
            raise ValidationError(_('Счёт закрытия не найден или недоступен.'))
        deposit.account = closure_accounts[deposit.account.pk]
        if destination_account is not None:
            destination_account = closure_accounts[destination_account.pk]
            if destination_account.is_archived:
                raise ValidationError(
                    _('Счёт назначения находится в архиве.'),
                )
        self._validate_closure_lifecycle(deposit, term, command)
        self._validate_closure_interest_amounts(command)
        forecast = self._resolve_closure_forecast(deposit, command.forecast_id)

        account_deltas = {deposit.account.pk: -command.principal}
        if destination_account is not None:
            account_deltas[destination_account.pk] = (
                command.principal + command.net
            )
        locked_accounts = self.balance_service.apply_account_deltas(
            account_deltas,
        )
        closed_account = locked_accounts.get(
            deposit.account.pk,
            closure_accounts[deposit.account.pk],
        )
        if closed_account.balance != 0:
            raise ValidationError(
                _('После закрытия остаток счёта вклада должен быть нулевым.'),
            )

        principal_event = self.deposit_repository.create_principal_event(
            deposit=deposit,
            type=DepositPrincipalEvent.Type.PLANNED_CLOSURE,
            amount=command.principal,
            posting_on=command.posting_on,
            effective_on=command.value_on,
            source_account=None,
            destination=command.destination,
            destination_account=destination_account,
            external_id=command.external_id,
        )
        interest_event = self.deposit_repository.create_capitalization_event(
            deposit=deposit,
            forecast=forecast,
            gross=command.gross,
            withholding=command.withholding,
            net=command.net,
            posting_on=command.posting_on,
            value_on=command.value_on,
            reason=str(_('Финальная выплата при плановом закрытии.')),
            destination=command.destination,
            destination_account=destination_account,
            is_final=True,
            external_id=command.external_id,
        )
        if forecast is not None:
            self.deposit_repository.confirm_forecast(forecast.pk)
        self.deposit_repository.delete_unconfirmed_forecasts(term.pk)
        self.deposit_repository.close_term(term.pk, command.value_on)
        self.account_repository.archive(deposit.account.pk)
        transaction.on_commit(
            lambda: invalidate_user_detailed_statistics_cache(command.user.pk),
        )
        self._create_audit(
            deposit=deposit,
            event_type=DepositAuditEvent.Type.CLOSURE,
            description=str(_('Плановое закрытие вклада.')),
        )
        return CloseMaturedDepositResult(
            principal_event=principal_event,
            interest_event=interest_event,
        )

    def _existing_closure_result(
        self,
        deposit_id: int,
        command: CloseMaturedDepositCommand,
    ) -> CloseMaturedDepositResult | None:
        principal_event = self.deposit_repository.get_planned_closure_event(
            deposit_id,
        )
        interest_event = self.deposit_repository.get_final_interest_event(
            deposit_id,
        )
        if principal_event is not None and interest_event is not None:
            if not self._closure_matches_command(
                principal_event,
                interest_event,
                command,
            ):
                raise ValidationError(
                    _('Вклад уже закрыт с другими фактическими данными.'),
                )
            return CloseMaturedDepositResult(
                principal_event=principal_event,
                interest_event=interest_event,
            )
        if principal_event is not None or interest_event is not None:
            raise ValidationError(
                _('История закрытия вклада содержит неполные данные.'),
            )
        return None

    @staticmethod
    def _closure_matches_command(
        principal_event: DepositPrincipalEvent,
        interest_event: DepositCapitalizationEvent,
        command: CloseMaturedDepositCommand,
    ) -> bool:
        return (
            principal_event.destination == command.destination
            and principal_event.destination_account_id
            == command.destination_account_id
            and principal_event.amount == command.principal
            and principal_event.posting_on == command.posting_on
            and principal_event.effective_on == command.value_on
            and interest_event.forecast_id == command.forecast_id
            and interest_event.gross == command.gross
            and interest_event.withholding == command.withholding
            and interest_event.net == command.net
            and interest_event.posting_on == command.posting_on
            and interest_event.value_on == command.value_on
        )

    def _validate_closure_lifecycle(
        self,
        deposit: Deposit,
        term: DepositTerm,
        command: CloseMaturedDepositCommand,
    ) -> None:
        if term.state != DepositTerm.State.MATURED:
            raise ValidationError(
                _('Плановое закрытие доступно только после окончания срока.'),
            )
        if (
            command.posting_on < term.matures_on
            or command.value_on < term.matures_on
        ):
            raise ValidationError(
                _('Фактические даты закрытия не могут быть раньше срока.'),
            )
        if command.principal < 0:
            raise ValidationError(
                _('Возвращаемое тело вклада не может быть отрицательным.'),
            )
        if command.principal != deposit.account.balance:
            raise ValidationError(
                _('Возвращаемое тело должно совпадать с остатком вклада.'),
            )

    def _resolve_closure_destination(
        self,
        deposit: Deposit,
        command: CloseMaturedDepositCommand | CloseDepositEarlyCommand,
    ) -> Account | None:
        if command.destination == InterestPayoutDestination.EXTERNAL:
            if command.destination_account_id is not None:
                raise ValidationError(
                    _('Для внешнего возврата счёт назначения не указывается.'),
                )
            return None
        if command.destination != InterestPayoutDestination.INTERNAL_ACCOUNT:
            raise ValidationError(_('Неизвестное назначение закрытия вклада.'))
        if command.destination_account_id is None:
            raise ValidationError(_('Выберите счёт для возврата вклада.'))
        destination = self.account_repository.get_by_id_and_user(
            command.destination_account_id,
            command.user,
        )
        if destination is None or destination.is_archived:
            raise ValidationError(
                _('Счёт назначения не найден или недоступен.'),
            )
        if destination.is_deposit:
            raise ValidationError(
                _('Закрытый вклад можно вернуть только на обычный счёт.'),
            )
        if destination.currency != deposit.account.currency:
            raise ValidationError(
                _('Счёт назначения должен быть в валюте вклада.'),
            )
        return destination

    def _validate_closure_interest_amounts(
        self,
        command: CloseMaturedDepositCommand | CloseDepositEarlyCommand,
    ) -> None:
        self._validate_interest_amounts(
            command.gross,
            command.withholding,
            command.net,
            allow_zero_net=True,
        )

    def _resolve_closure_forecast(
        self,
        deposit: Deposit,
        forecast_id: int | None,
    ) -> DepositInterestForecast | None:
        if forecast_id is None:
            return None
        try:
            forecast = self.deposit_repository.get_forecast_for_update(
                forecast_id,
                deposit.current_term.pk,
            )
        except DepositInterestForecast.DoesNotExist as error:
            raise ValidationError(
                _('Ожидаемая финальная выплата не найдена.'),
            ) from error
        if forecast.confirmed:
            raise ValidationError(
                _('Эта ожидаемая выплата уже подтверждена.'),
            )
        if forecast.period_ends_on != deposit.current_term.matures_on:
            raise ValidationError(
                _('Для закрытия выберите финальную ожидаемую выплату.'),
            )
        return forecast

    def _resolve_interest_destination(
        self,
        deposit: Deposit,
        command: CapitalizeInterestCommand,
    ) -> Account | None:
        if command.destination not in tuple(
            choice.value for choice in DepositCapitalizationEvent.Destination
        ):
            raise ValidationError(
                _('Неизвестное назначение выплаты процентов.'),
            )
        if (
            command.destination
            != DepositCapitalizationEvent.Destination.INTERNAL_ACCOUNT
        ):
            if command.destination_account_id is not None:
                raise ValidationError(
                    _('Счёт можно указать только для внутренней выплаты.'),
                )
            return None
        if command.destination_account_id is None:
            raise ValidationError(
                _('Выберите собственный счёт для выплаты процентов.'),
            )
        account = self.account_repository.get_by_id_and_user(
            command.destination_account_id,
            command.user,
        )
        if account is None:
            raise ValidationError(
                _(
                    'Счёт выплаты не найден или принадлежит другому '
                    'пользователю.',
                ),
            )
        if account.is_archived:
            raise ValidationError(_('Счёт выплаты находится в архиве.'))
        if account.pk == deposit.account.pk:
            raise ValidationError(
                _('Для внутренней выплаты выберите другой собственный счёт.'),
            )
        if account.currency != deposit.account.currency:
            raise ValidationError(
                _('Валюта счёта выплаты должна совпадать с валютой вклада.'),
            )
        return account

    def _validate_capitalization_amounts(
        self,
        command: CapitalizeInterestCommand,
    ) -> None:
        self._validate_interest_amounts(
            command.gross,
            command.withholding,
            command.net,
            allow_zero_net=False,
        )

    @staticmethod
    def _validate_interest_amounts(
        gross: Decimal,
        withholding: Decimal,
        net: Decimal,
        *,
        allow_zero_net: bool,
    ) -> None:
        amounts = (gross, withholding, net)
        if min(amounts) < 0:
            raise ValidationError(
                _('Суммы процентов не могут быть отрицательными.'),
            )
        if not allow_zero_net and net == 0:
            raise ValidationError(_('Чистый доход должен быть больше нуля.'))
        if any(
            amount != amount.quantize(constants.MIN_MONEY_AMOUNT)
            for amount in amounts
        ):
            raise ValidationError(
                _('Суммы процентов должны иметь точность до копеек.'),
            )
        if gross - withholding != net:
            raise ValidationError(
                _('Чистые проценты должны равняться gross минус удержание.'),
            )

    def _resolve_capitalization_forecast(
        self,
        deposit: Deposit,
        command: CapitalizeInterestCommand,
    ) -> DepositInterestForecast | None:
        if command.forecast_id is None:
            if not command.reason.strip():
                raise ValidationError(
                    _('Для внеплановой выплаты укажите причину.'),
                )
            return None
        try:
            forecast = self.deposit_repository.get_forecast_for_update(
                command.forecast_id,
                deposit.current_term.pk,
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
        if term.state == DepositTerm.State.CLOSED:
            raise ValidationError(
                _('Прогноз закрытого вклада нельзя изменить.'),
            )
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
                amount=self._signed_principal_amount(event),
            )
            for event in term.deposit.principal_events.all()
        ]
        capitalization_changes = [
            PrincipalChange(
                effective_on=ce.value_on,
                amount=-ce.net if ce.reversal_of_id else ce.net,
            )
            for ce in term.deposit.capitalization_events.filter(
                destination=(
                    DepositCapitalizationEvent.Destination.CAPITALIZATION
                ),
            )
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

    def _check_principal_idempotency(
        self,
        *,
        deposit_id: int,
        external_id: str,
        event_type: str,
        amount: Decimal,
        effective_on: 'date',
    ) -> DepositPrincipalEvent | None:
        existing = self.deposit_repository.get_principal_event_by_external_id(
            deposit_id,
            external_id,
        )
        if existing is None:
            return None
        if existing.reversal_of_id is not None:
            raise ValidationError(
                _(
                    'Компенсирующее событие нельзя повторно провести '
                    'с тем же внешним идентификатором.',
                ),
            )
        if hasattr(existing, 'reversal') and existing.reversal is not None:
            raise ValidationError(
                _(
                    'Событие с внешним идентификатором «{external_id}» '
                    'уже аннулировано.',
                ).format(external_id=external_id),
            )
        if (
            existing.type != event_type
            or existing.amount != amount
            or existing.effective_on != effective_on
        ):
            raise ValidationError(
                _(
                    'Событие с внешним идентификатором «{external_id}» '
                    'уже существует с другими параметрами.',
                ).format(external_id=external_id),
            )
        return existing

    def _check_capitalization_idempotency(
        self,
        *,
        deposit_id: int,
        external_id: str,
        gross: Decimal,
        withholding: Decimal,
        net: Decimal,
        posting_on: 'date',
        value_on: 'date',
    ) -> DepositCapitalizationEvent | None:
        existing = (
            self.deposit_repository.get_capitalization_event_by_external_id(
                deposit_id,
                external_id,
            )
        )
        if existing is None:
            return None
        if existing.reversal_of_id is not None:
            raise ValidationError(
                _(
                    'Компенсирующее событие нельзя повторно провести '
                    'с тем же внешним идентификатором.',
                ),
            )
        if hasattr(existing, 'reversal') and existing.reversal is not None:
            raise ValidationError(
                _(
                    'Событие с внешним идентификатором «{external_id}» '
                    'уже аннулировано.',
                ).format(external_id=external_id),
            )
        if (
            existing.gross != gross
            or existing.withholding != withholding
            or existing.net != net
            or existing.posting_on != posting_on
            or existing.value_on != value_on
        ):
            raise ValidationError(
                _(
                    'Событие с внешним идентификатором «{external_id}» '
                    'уже существует с другими параметрами.',
                ).format(external_id=external_id),
            )
        return existing

    def _create_audit(
        self,
        deposit: 'Deposit',
        event_type: str,
        description: str,
    ) -> None:
        self.deposit_repository.create_audit_event(
            deposit=deposit,
            event_type=event_type,
            description=description,
        )

    def reconcile_deposit(
        self,
        deposit_id: int,
        user: 'User',
    ) -> dict[str, object]:
        deposit = self.deposit_repository.get_by_id_and_user(
            deposit_id,
            user,
        )
        events = deposit.principal_events.all()
        calculated = Decimal()
        for event in events:
            calculated += self._signed_principal_amount(event)
        for cap_event in deposit.capitalization_events.filter(
            destination=(DepositCapitalizationEvent.Destination.CAPITALIZATION),
        ):
            net = cap_event.net
            calculated += -net if cap_event.reversal_of_id else net
        account = deposit.account
        discrepancy = account.balance - calculated
        now = timezone.now()
        account.last_reconciled_at = now
        account.save(update_fields=['last_reconciled_at'])
        return {
            'calculated_balance': calculated,
            'account_balance': account.balance,
            'discrepancy': discrepancy,
            'last_reconciled_at': now,
        }
