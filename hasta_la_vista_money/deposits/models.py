from typing import TYPE_CHECKING, Any, ClassVar

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.bank_constants import BANK_CHOICES
from hasta_la_vista_money.finance_account.models import Account


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
    bank = models.CharField(
        max_length=20,
        choices=BANK_CHOICES,
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
    if TYPE_CHECKING:
        rate_periods: models.Manager['DepositRatePeriod']

    class State(models.TextChoices):
        PLANNED = 'planned', _('Запланирован')
        ACTIVE = 'active', _('Активен')
        MATURED = 'matured', _('Срок истёк')

    class RateKind(models.TextChoices):
        FIXED = 'fixed', _('Фиксированная')
        FLOATING = 'floating', _('Плавающая')

    deposit = models.ForeignKey(
        Deposit,
        on_delete=models.CASCADE,
        related_name='terms',
    )
    opened_on = models.DateField(verbose_name=_('Дата открытия'))
    matures_on = models.DateField(verbose_name=_('Дата окончания'))
    is_current = models.BooleanField(default=True)
    rate_kind = models.CharField(
        max_length=10,
        choices=RateKind.choices,
        default=RateKind.FIXED,
        verbose_name=_('Тип ставки'),
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
        ]

    @property
    def state(self) -> str:
        today = timezone.localdate()
        if today < self.opened_on:
            return self.State.PLANNED
        if today > self.matures_on:
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
            return self.rate_periods.get(
                starts_on=self.opened_on,
                ends_on=self.matures_on,
            )
        return None

    def has_defined_current_rate(self) -> bool:
        return self.current_rate is not None


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
    source_account = models.ForeignKey(
        Account,
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        related_name='deposit_funding_events',
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
                ),
                name='deposit_principal_event_amount_valid',
            ),
            models.CheckConstraint(
                condition=(
                    Q(type='funding', source_account__isnull=False)
                    | Q(
                        type='opening_position',
                        source_account__isnull=True,
                    )
                ),
                name='deposit_principal_event_source_valid',
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
