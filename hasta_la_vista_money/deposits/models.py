from typing import ClassVar

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
    class State(models.TextChoices):
        PLANNED = 'planned', _('Запланирован')
        ACTIVE = 'active', _('Активен')
        MATURED = 'matured', _('Срок истёк')

    deposit = models.ForeignKey(
        Deposit,
        on_delete=models.CASCADE,
        related_name='terms',
    )
    opened_on = models.DateField(verbose_name=_('Дата открытия'))
    matures_on = models.DateField(verbose_name=_('Дата окончания'))
    is_current = models.BooleanField(default=True)

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
    def current_rate(self) -> 'DepositRatePeriod':
        today = timezone.localdate()
        rate = self.rate_periods.filter(
            starts_on__lte=today,
            ends_on__gte=today,
        ).first()
        return rate or self.rate_periods.get(
            starts_on=self.opened_on,
            ends_on=self.matures_on,
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
