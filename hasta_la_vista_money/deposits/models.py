from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from datetime import date

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.currencies import (
    get_currency_precision,
)
from hasta_la_vista_money.finance_account.models import Account, Bank


class InterestPayoutDestination(models.TextChoices):
    CAPITALIZATION = 'capitalization', _('Капитализация')
    INTERNAL_ACCOUNT = 'internal_account', _('На собственный счёт')
    EXTERNAL = 'external', _('Внешнему получателю')


class Deposit(models.Model):
    if TYPE_CHECKING:
        terms: models.Manager['DepositTerm']

    account = models.OneToOneField(
        Account,
        on_delete=models.PROTECT,
        related_name='deposit',
    )
    name = models.CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
        verbose_name=_('Название вклада'),
    )
    bank = models.ForeignKey(
        Bank,
        on_delete=models.PROTECT,
        related_name='deposits',
        verbose_name=_('Банк'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: ClassVar[list[str]] = ['name']
        verbose_name = _('Срочный вклад')
        verbose_name_plural = _('Срочные вклады')

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse('deposits:detail', args=[self.pk])

    @property
    def current_term(self) -> 'DepositTerm':
        return self.terms.get(is_current=True)


class DepositTerm(models.Model):
    PayoutDestination = InterestPayoutDestination

    if TYPE_CHECKING:
        rate_periods: models.Manager['DepositRatePeriod']
        payout_schedule_dates: models.Manager['DepositPayoutScheduleDate']
        interest_forecasts: models.Manager['DepositInterestForecast']

    class State(models.TextChoices):
        PLANNED = 'planned', _('Запланирован')
        ACTIVE = 'active', _('Активен')
        MATURED = 'matured', _('Срок истёк')
        CLOSED = 'closed', _('Закрыт')

    class RateKind(models.TextChoices):
        FIXED = 'fixed', _('Фиксированная')
        FLOATING = 'floating', _('Плавающая')

    class DayCountConvention(models.TextChoices):
        ACTUAL_ACTUAL = 'actual_actual', _('Actual/Actual')
        ACTUAL_365 = 'actual_365', _('Actual/365')

    class PayoutScheduleKind(models.TextChoices):
        MONTHLY = 'monthly', _('Ежемесячно')
        MATURITY = 'maturity', _('В конце срока')
        CUSTOM = 'custom', _('Индивидуальное расписание')

    class BusinessDayConvention(models.TextChoices):
        NONE = 'none', _('Без переноса')
        PRECEDING = 'preceding', _('На предыдущий рабочий день')
        FOLLOWING = 'following', _('На следующий рабочий день')

    class EarlyClosureRecalculationScope(models.TextChoices):
        WHOLE_TERM = 'whole_term', _('Весь срок')
        CURRENT_PERIOD = 'current_period', _('Текущий период')
        WITHDRAWN_AMOUNT = 'withdrawn_amount', _('Снятая сумма')
        UNSUPPORTED = 'unsupported', _('Формула банка не поддерживается')

    deposit = models.ForeignKey(
        Deposit,
        on_delete=models.CASCADE,
        related_name='terms',
    )
    opened_on = models.DateField(verbose_name=_('Дата открытия'))
    interest_accrual_starts_on = models.DateField(
        null=True,
        blank=True,
        verbose_name=_('Дата начала начисления процентов'),
        help_text=_(
            'Если не указана, начисление начинается с даты открытия.',
        ),
    )
    matures_on = models.DateField(verbose_name=_('Дата окончания'))
    is_current = models.BooleanField(default=True)
    rate_kind = models.CharField(
        max_length=10,
        choices=RateKind.choices,
        default=RateKind.FIXED,
        verbose_name=_('Тип ставки'),
    )
    day_count_convention = models.CharField(
        max_length=20,
        choices=DayCountConvention.choices,
        default=DayCountConvention.ACTUAL_ACTUAL,
        verbose_name=_('Метод расчёта дней'),
    )
    accrual_start_included = models.BooleanField(
        default=True,
        verbose_name=_('Учитывать день поступления средств'),
    )
    accrual_end_included = models.BooleanField(
        default=False,
        verbose_name=_('Учитывать день возврата вклада'),
    )
    payout_schedule_kind = models.CharField(
        max_length=10,
        choices=PayoutScheduleKind.choices,
        default=PayoutScheduleKind.MATURITY,
        verbose_name=_('Расписание выплат'),
    )
    interest_payout_destination = models.CharField(
        max_length=20,
        choices=InterestPayoutDestination.choices,
        default=InterestPayoutDestination.CAPITALIZATION,
        verbose_name=_('Обычный способ выплаты процентов'),
    )
    business_day_convention = models.CharField(
        max_length=10,
        choices=BusinessDayConvention.choices,
        default=BusinessDayConvention.NONE,
        verbose_name=_('Перенос выплаты на рабочий день'),
    )
    rounding_rule = models.CharField(
        max_length=20,
        default='ROUND_HALF_UP',
        verbose_name=_('Правило денежного округления'),
        help_text=_(
            'Константа округления из модуля decimal '
            '(ROUND_HALF_UP, ROUND_HALF_EVEN и т.д.).',
        ),
    )
    withdrawal_allowed = models.BooleanField(
        default=False,
        verbose_name=_('Разрешено частичное снятие'),
    )
    minimum_withdrawal_amount = models.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        null=True,
        blank=True,
        verbose_name=_('Минимальная сумма снятия'),
    )
    maximum_withdrawal_amount = models.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        null=True,
        blank=True,
        verbose_name=_('Максимальная сумма снятия'),
    )
    withdrawal_deadline = models.DateField(
        null=True,
        blank=True,
        verbose_name=_('Крайний срок снятия'),
    )
    minimum_balance = models.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        default=0,
        verbose_name=_('Неснижаемый остаток'),
    )
    top_up_allowed = models.BooleanField(
        default=False,
        verbose_name=_('Разрешено пополнение'),
    )
    minimum_top_up_amount = models.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        null=True,
        blank=True,
        verbose_name=_('Минимальная сумма пополнения'),
    )
    maximum_top_up_amount = models.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        null=True,
        blank=True,
        verbose_name=_('Максимальная сумма пополнения'),
    )
    top_up_deadline = models.DateField(
        null=True,
        blank=True,
        verbose_name=_('Крайний срок пополнения'),
    )
    maximum_balance = models.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        null=True,
        blank=True,
        verbose_name=_('Максимальный остаток после пополнения'),
    )
    early_closure_annual_rate = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_('Ставка досрочного расторжения'),
    )
    early_closure_recalculation_scope = models.CharField(
        max_length=20,
        choices=EarlyClosureRecalculationScope.choices,
        default=EarlyClosureRecalculationScope.UNSUPPORTED,
        verbose_name=_('Область пересчёта при досрочном расторжении'),
    )
    early_closure_withdrawn_amount = models.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_('Сумма для пересчёта при досрочном расторжении'),
    )
    closed_on = models.DateField(
        null=True,
        blank=True,
        verbose_name=_('Фактическая дата закрытия'),
    )

    class Meta:
        ordering: ClassVar[list[str]] = ['opened_on']
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(matures_on__gte=models.F('opened_on')),
                name='deposit_term_dates_valid',
            ),
            models.UniqueConstraint(
                fields=['deposit'],
                condition=Q(is_current=True),
                name='one_current_term_per_deposit',
            ),
            models.CheckConstraint(
                condition=(
                    Q(closed_on__isnull=True)
                    | Q(closed_on__gte=models.F('opened_on'))
                ),
                name='deposit_closure_not_before_opening',
            ),
        ]

    @property
    def accrual_date(self) -> 'date':
        """Date from which interest accrual begins.

        Falls back to opened_on when interest_accrual_starts_on is not set.
        """
        return self.interest_accrual_starts_on or self.opened_on

    @property
    def money_precision(self) -> Decimal:
        """Smallest currency unit for the deposit account's currency.

        Derived from the account's currency code, e.g. 0.01 for RUB/USD,
        1 for JPY/KRW, 0.001 for BHD/KWD/OMR.
        """
        return get_currency_precision(self.deposit.account.currency)

    @property
    def state(self) -> str:
        if self.closed_on is not None:
            return self.State.CLOSED
        today = timezone.localdate()
        if today < self.opened_on:
            return self.State.PLANNED
        if today >= self.matures_on:
            return self.State.MATURED
        return self.State.ACTIVE

    @property
    def state_label(self) -> str:
        return str(self.State(self.state).label)

    @property
    def current_rate(self) -> 'DepositRatePeriod | None':
        today = timezone.localdate()
        rate = self.rate_periods.filter(
            starts_on__lte=today,
            ends_on__gte=today,
        ).first()
        if rate is not None:
            return rate
        if self.rate_kind == self.RateKind.FIXED:
            accrual = self.accrual_date
            return self.rate_periods.filter(
                starts_on=accrual,
                ends_on=self.matures_on,
            ).first()
        return None

    def has_defined_current_rate(self) -> bool:
        return self.current_rate is not None

    @property
    def liquid_amount(self) -> Decimal:
        balance = self.deposit.account.balance
        today = timezone.localdate()
        if self.state == self.State.MATURED:
            return balance
        if (
            not self.withdrawal_allowed
            or self.state != self.State.ACTIVE
            or (
                self.withdrawal_deadline is not None
                and today > self.withdrawal_deadline
            )
        ):
            return Decimal()
        available = max(balance - self.minimum_balance, Decimal())
        if self.maximum_withdrawal_amount is not None:
            available = min(available, self.maximum_withdrawal_amount)
        if (
            self.minimum_withdrawal_amount is not None
            and available < self.minimum_withdrawal_amount
        ):
            return Decimal()
        return available

    @property
    def next_payout(self) -> 'DepositInterestForecast | None':
        today = timezone.localdate()
        forecasts = (
            forecast
            for forecast in self.interest_forecasts.all()
            if not forecast.confirmed and forecast.payout_on >= today
        )
        return min(
            forecasts,
            key=lambda forecast: forecast.payout_on,
            default=None,
        )


class DepositRatePeriod(models.Model):
    term = models.ForeignKey(
        DepositTerm,
        on_delete=models.CASCADE,
        related_name='rate_periods',
    )
    starts_on = models.DateField(verbose_name=_('Начало периода ставки'))
    ends_on = models.DateField(verbose_name=_('Окончание периода ставки'))
    annual_rate = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        validators=[MinValueValidator(constants.MIN_ANNUAL_RATE)],
        verbose_name=_('Годовая ставка'),
    )
    note = models.CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
        blank=True,
        default='',
        verbose_name=_('Пояснение к ставке'),
    )

    class Meta:
        ordering: ClassVar[list[str]] = ['starts_on']
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=['term', 'starts_on', 'ends_on'],
                name='deposit_rate_period_range_idx',
            ),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(ends_on__gte=models.F('starts_on')),
                name='deposit_rate_period_dates_valid',
            ),
            models.CheckConstraint(
                condition=Q(annual_rate__gt=0),
                name='deposit_annual_rate_positive',
            ),
        ]


class DepositRenewalEventQuerySet(
    models.QuerySet['DepositRenewalEvent'],
):
    def update(self, **kwargs: Any) -> int:
        raise ValidationError(
            _('Подтверждённую пролонгацию нельзя изменить.'),
        )

    def delete(self) -> tuple[int, dict[str, int]]:
        raise ValidationError(
            _('Подтверждённую пролонгацию нельзя удалить.'),
        )


class DepositRenewalEvent(models.Model):
    deposit = models.ForeignKey(
        Deposit,
        on_delete=models.PROTECT,
        related_name='renewal_events',
    )
    previous_term = models.ForeignKey(
        DepositTerm,
        on_delete=models.PROTECT,
        related_name='renewals_from',
    )
    renewed_term = models.ForeignKey(
        DepositTerm,
        on_delete=models.PROTECT,
        related_name='renewal_events',
    )
    effective_on = models.DateField(verbose_name=_('Дата пролонгации'))
    reversal_of = models.OneToOneField(
        'self',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='reversal',
        verbose_name=_('Аннулированная пролонгация'),
    )
    reversal_reason = models.CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
        blank=True,
        default='',
        verbose_name=_('Причина аннулирования'),
    )
    confirmed_at = models.DateTimeField(auto_now_add=True)

    objects = DepositRenewalEventQuerySet.as_manager()

    class Meta:
        ordering: ClassVar[list[str]] = ['effective_on', 'pk']
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=(
                    Q(reversal_of__isnull=True, reversal_reason='')
                    | Q(
                        reversal_of__isnull=False,
                        reversal_reason__gt='',
                    )
                ),
                name='deposit_renewal_reversal_reason_valid',
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                _('Подтверждённую пролонгацию нельзя изменить.'),
            )
        super().save(*args, **kwargs)

    def delete(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError(
            _('Подтверждённую пролонгацию нельзя удалить.'),
        )


class DepositPrincipalEventQuerySet(
    models.QuerySet['DepositPrincipalEvent'],
):
    """QuerySet that prevents bulk mutations of confirmed principal events.

    Raises:
        ValidationError: On any update or delete operation.
    """

    def update(self, **kwargs: Any) -> int:
        raise ValidationError(
            _('Подтверждённое событие вклада нельзя изменить.'),
        )

    def delete(self) -> tuple[int, dict[str, int]]:
        raise ValidationError(
            _('Подтверждённое событие вклада нельзя удалить.'),
        )


class DepositPrincipalEvent(models.Model):
    """Immutable record of a principal movement for a term deposit.

    Each event represents either a funding transfer or an opening position
    and cannot be modified or deleted after creation.
    """

    class Type(models.TextChoices):
        FUNDING = 'funding', _('Финансирование')
        OPENING_POSITION = 'opening_position', _('Начальная позиция')
        TOP_UP = 'top_up', _('Пополнение')
        WITHDRAWAL = 'withdrawal', _('Снятие')
        PLANNED_CLOSURE = 'planned_closure', _('Плановое закрытие')
        EARLY_CLOSURE = 'early_closure', _('Досрочное закрытие')

    deposit = models.ForeignKey(
        Deposit,
        on_delete=models.PROTECT,
        related_name='principal_events',
    )
    type = models.CharField(max_length=20, choices=Type.choices)
    amount = models.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        validators=[MinValueValidator(0)],
    )
    effective_on = models.DateField(verbose_name=_('Дата события'))
    posting_on = models.DateField(
        null=True,
        blank=True,
        verbose_name=_('Дата проводки'),
    )
    destination = models.CharField(
        max_length=20,
        choices=InterestPayoutDestination.choices,
        null=True,
        blank=True,
        verbose_name=_('Назначение возврата тела'),
    )
    source_account = models.ForeignKey(
        Account,
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        related_name='deposit_funding_events',
    )
    destination_account = models.ForeignKey(
        Account,
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        related_name='deposit_withdrawal_events',
    )
    exception_reason = models.CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
        blank=True,
        default='',
        verbose_name=_('Причина исключения'),
    )
    external_id = models.CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
        null=True,
        blank=True,
        verbose_name=_('Внешний идентификатор'),
        help_text=_('Уникальный в пределах вклада ключ банковского факта'),
    )
    reversal_of = models.OneToOneField(
        'self',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='reversal',
        verbose_name=_('Аннулированное событие'),
    )
    reversal_reason = models.CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
        blank=True,
        default='',
        verbose_name=_('Причина аннулирования'),
    )
    confirmed_at = models.DateTimeField(auto_now_add=True)

    objects = DepositPrincipalEventQuerySet.as_manager()

    class Meta:
        ordering: ClassVar[list[str]] = ['effective_on', 'pk']
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=(
                    Q(type='funding', amount__gt=0)
                    | Q(type='opening_position', amount__gte=0)
                    | Q(type='top_up', amount__gt=0)
                    | Q(type='withdrawal', amount__gt=0)
                    | Q(type='planned_closure', amount__gte=0)
                    | Q(type='early_closure', amount__gte=0)
                ),
                name='deposit_principal_event_amount_valid',
            ),
            models.CheckConstraint(
                condition=(
                    Q(type='funding', source_account__isnull=False)
                    | Q(type='top_up', source_account__isnull=False)
                    | Q(
                        type='opening_position',
                        source_account__isnull=True,
                    )
                    | Q(
                        type='withdrawal',
                        source_account__isnull=True,
                        destination_account__isnull=False,
                    )
                    | Q(
                        type='planned_closure',
                        source_account__isnull=True,
                        destination=(
                            InterestPayoutDestination.INTERNAL_ACCOUNT
                        ),
                        destination_account__isnull=False,
                    )
                    | Q(
                        type='planned_closure',
                        source_account__isnull=True,
                        destination=InterestPayoutDestination.EXTERNAL,
                        destination_account__isnull=True,
                    )
                    | Q(
                        type='early_closure',
                        source_account__isnull=True,
                        destination=(
                            InterestPayoutDestination.INTERNAL_ACCOUNT
                        ),
                        destination_account__isnull=False,
                    )
                    | Q(
                        type='early_closure',
                        source_account__isnull=True,
                        destination=InterestPayoutDestination.EXTERNAL,
                        destination_account__isnull=True,
                    )
                ),
                name='deposit_principal_event_source_valid',
            ),
            models.CheckConstraint(
                condition=(
                    Q(reversal_of__isnull=True, reversal_reason='')
                    | Q(
                        reversal_of__isnull=False,
                        reversal_reason__gt='',
                    )
                ),
                name='deposit_principal_reversal_reason_valid',
            ),
            models.UniqueConstraint(
                fields=['deposit', 'external_id'],
                condition=Q(external_id__isnull=False),
                name='deposit_principal_external_id_unique',
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Save only on creation; reject updates to confirmed events.

        Raises:
            ValidationError: If the event already exists in the database.
        """
        if not self._state.adding:
            raise ValidationError(
                _('Подтверждённое событие вклада нельзя изменить.'),
            )
        super().save(*args, **kwargs)

    def delete(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> tuple[int, dict[str, int]]:
        """Prevent deletion of confirmed principal events.

        Raises:
            ValidationError: Always — confirmed events are immutable.
        """
        raise ValidationError(
            _('Подтверждённое событие вклада нельзя удалить.'),
        )


class DepositPayoutScheduleDate(models.Model):
    """A single user-defined payout date for a term's custom schedule.

    Only used when the owning term's payout_schedule_kind is CUSTOM.
    """

    term = models.ForeignKey(
        DepositTerm,
        on_delete=models.CASCADE,
        related_name='payout_schedule_dates',
    )
    payout_on = models.DateField(verbose_name=_('Дата выплаты'))

    class Meta:
        ordering: ClassVar[list[str]] = ['payout_on']
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=['term', 'payout_on'],
                name='deposit_payout_schedule_date_unique',
            ),
        ]


class DepositInterestForecast(models.Model):
    """A projected interest payment for a deposit term.

    Purely informational: creating or recalculating forecasts never
    changes Account.balance, actual income/expense, or KPIs. Recalculating
    a term's forecast replaces only rows where confirmed is False.
    """

    term = models.ForeignKey(
        DepositTerm,
        on_delete=models.CASCADE,
        related_name='interest_forecasts',
    )
    payout_on = models.DateField(verbose_name=_('Ожидаемая дата выплаты'))
    amount = models.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        verbose_name=_('Ожидаемая сумма'),
    )
    period_starts_on = models.DateField(
        verbose_name=_('Начало периода начисления'),
    )
    period_ends_on = models.DateField(
        verbose_name=_('Конец периода начисления'),
    )
    is_rate_undefined = models.BooleanField(
        default=False,
        verbose_name=_('Ставка периода не определена'),
    )
    is_date_tentative = models.BooleanField(
        default=False,
        verbose_name=_('Дата ориентировочна'),
    )
    confirmed = models.BooleanField(
        default=False,
        verbose_name=_('Подтверждено фактической выплатой'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: ClassVar[list[str]] = ['payout_on', 'pk']
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(amount__gte=0),
                name='deposit_interest_forecast_amount_valid',
            ),
            models.CheckConstraint(
                condition=Q(period_ends_on__gte=models.F('period_starts_on')),
                name='deposit_interest_forecast_period_valid',
            ),
        ]

    def __str__(self) -> str:
        return f'{date_format(self.payout_on, "d.m.Y")} — {self.amount}'


class DepositCapitalizationEventQuerySet(
    models.QuerySet['DepositCapitalizationEvent'],
):
    def update(self, **kwargs: Any) -> int:
        raise ValidationError(
            _('Подтверждённую выплату процентов нельзя изменить.'),
        )

    def delete(self) -> tuple[int, dict[str, int]]:
        raise ValidationError(
            _('Подтверждённую выплату процентов нельзя удалить.'),
        )


class DepositCapitalizationEvent(models.Model):
    Destination = InterestPayoutDestination

    deposit = models.ForeignKey(
        Deposit,
        on_delete=models.PROTECT,
        related_name='capitalization_events',
    )
    forecast = models.ForeignKey(
        DepositInterestForecast,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='capitalization_event',
    )
    destination = models.CharField(
        max_length=20,
        choices=InterestPayoutDestination.choices,
        default=InterestPayoutDestination.CAPITALIZATION,
        verbose_name=_('Фактическое назначение выплаты'),
    )
    destination_account = models.ForeignKey(
        Account,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='deposit_interest_payouts',
        verbose_name=_('Счёт назначения'),
    )
    gross = models.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        validators=[MinValueValidator(0)],
    )
    withholding = models.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        validators=[MinValueValidator(0)],
    )
    net = models.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        validators=[MinValueValidator(0)],
    )
    posting_on = models.DateField(verbose_name=_('Дата проводки'))
    value_on = models.DateField(verbose_name=_('Дата валютирования'))
    reason = models.CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
        blank=True,
        default='',
        verbose_name=_('Причина внеплановой выплаты'),
    )
    is_final = models.BooleanField(
        default=False,
        verbose_name=_('Финальная выплата при закрытии'),
    )
    prior_interest_adjustment = models.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        default=0,
        verbose_name=_('Корректировка ранее выплаченных процентов'),
    )
    external_id = models.CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
        null=True,
        blank=True,
        verbose_name=_('Внешний идентификатор'),
        help_text=_('Уникальный в пределах вклада ключ банковского факта'),
    )
    reversal_of = models.OneToOneField(
        'self',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='reversal',
        verbose_name=_('Аннулированная выплата'),
    )
    reversal_reason = models.CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
        blank=True,
        default='',
        verbose_name=_('Причина аннулирования'),
    )
    confirmed_at = models.DateTimeField(auto_now_add=True)

    objects = DepositCapitalizationEventQuerySet.as_manager()

    class Meta:
        ordering: ClassVar[list[str]] = ['value_on', 'pk']
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(gross__gte=0),
                name='deposit_capitalization_gross_non_negative',
            ),
            models.CheckConstraint(
                condition=Q(withholding__gte=0),
                name='deposit_capitalization_withholding_non_negative',
            ),
            models.CheckConstraint(
                condition=Q(net__gte=0),
                name='deposit_capitalization_net_non_negative',
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        destination=(
                            InterestPayoutDestination.INTERNAL_ACCOUNT
                        ),
                        destination_account__isnull=False,
                    )
                    | Q(
                        destination__in=(
                            InterestPayoutDestination.CAPITALIZATION,
                            InterestPayoutDestination.EXTERNAL,
                        ),
                        destination_account__isnull=True,
                    )
                ),
                name='deposit_interest_destination_account_valid',
            ),
            models.UniqueConstraint(
                fields=['forecast'],
                condition=Q(forecast__isnull=False),
                name='one_actual_interest_event_per_forecast',
            ),
            models.CheckConstraint(
                condition=(
                    Q(reversal_of__isnull=True, reversal_reason='')
                    | Q(
                        reversal_of__isnull=False,
                        reversal_reason__gt='',
                    )
                ),
                name='deposit_interest_reversal_reason_valid',
            ),
            models.UniqueConstraint(
                fields=['deposit', 'external_id'],
                condition=Q(external_id__isnull=False),
                name='deposit_interest_external_id_unique',
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                _('Подтверждённую выплату процентов нельзя изменить.'),
            )
        super().save(*args, **kwargs)

    def delete(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError(
            _('Подтверждённую выплату процентов нельзя удалить.'),
        )


class DepositAuditEvent(models.Model):
    """Immutable audit record for deposit lifecycle operations.

    Records the fact of conversion, confirmation, exclusion,
    cancellation, closure, and renewal without storing sensitive
    financial details (amounts, account numbers).
    """

    class Type(models.TextChoices):
        CONVERSION = 'conversion', _('Преобразование счёта')
        CONFIRMATION = 'confirmation', _('Подтверждение выплаты процентов')
        EXCLUSION = 'exclusion', _('Операция вне условий')
        CANCELLATION = 'cancellation', _('Аннулирование события')
        CLOSURE = 'closure', _('Закрытие вклада')
        RENEWAL = 'renewal', _('Пролонгация вклада')
        SCHEDULE_CORRECTION = (
            'schedule_correction',
            _('Исправление расписания выплат'),
        )

    deposit = models.ForeignKey(
        Deposit,
        on_delete=models.PROTECT,
        related_name='audit_events',
        verbose_name=_('Вклад'),
    )
    event_type = models.CharField(
        max_length=20,
        choices=Type.choices,
        verbose_name=_('Тип операции'),
    )
    description = models.CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
        verbose_name=_('Описание'),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Дата записи'),
    )

    class Meta:
        ordering: ClassVar[list[str]] = ['-created_at']
        verbose_name = _('Запись аудита вклада')
        verbose_name_plural = _('Аудит вкладов')
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=['deposit', 'event_type']),
        ]

    def __str__(self) -> str:
        return f'{self.get_event_type_display()} — {self.description[:80]}'
