from decimal import Decimal

from django.db import models
from django.urls import reverse
from django.utils.translation import gettext as _
from hasta_la_vista_money import constants
from hasta_la_vista_money.users.models import User


class Account(models.Model):
    CURRENCY_LIST = [
        ('RUB', _('Российский рубль')),
        ('USD', _('Доллар США')),
        ('EUR', _('Евро')),
        ('GBP', _('Британский фунт')),
        ('CZK', _('Чешская крона')),
        ('PLN', _('Польский злотый')),
        ('TRY', _('Турецкая лира')),
        ('CNH', _('Китайский юань')),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='finance_account_users',
    )
    name_account = models.CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
        default=_('Основной счёт'),
    )
    balance = models.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=2,
        default=0,
    )
    currency = models.CharField(choices=CURRENCY_LIST)
    created_at = models.DateTimeField(
        auto_now_add=True,
        null=True,
        blank=True,
        verbose_name=_('Date created'),
    )

    class Meta:
        db_table = 'account'
        ordering = ['name_account']
        indexes = [models.Index(fields=['name_account'])]

    def __str__(self) -> str:
        return f'{self.name_account}'

    def get_absolute_url(self) -> str:
        return reverse('finance_account:change', args=[self.id])

    def transfer_money(self, to_account: 'Account', amount: Decimal) -> bool:
        if amount <= self.balance:
            self.balance -= amount
            to_account.balance += amount
            self.save()
            to_account.save()
            return True
        return False


class TransferMoneyLog(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='transfer_money',
    )
    from_account = models.ForeignKey(
        Account,
        related_name='from_account',
        on_delete=models.CASCADE,
    )
    to_account = models.ForeignKey(
        Account,
        related_name='to_account',
        on_delete=models.CASCADE,
    )
    amount = models.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
    )
    exchange_date = models.DateTimeField()
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(
        auto_now_add=True,
        null=True,
        blank=True,
        verbose_name='Date created',
    )

    class Meta:
        ordering = ['-exchange_date']

    def __str__(self) -> str:
        return _(
            ''.join(
                (
                    f'{self.exchange_date:%d-%m-%Y %H:%M}. '
                    f'Перевод суммы {self.amount} '
                    f'со счёта "{self.from_account}" '
                    f'на счёт "{self.to_account}". ',
                ),
            ),
        )
