from datetime import date
from typing import ClassVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.currencies import (
    currency_choices,
    get_default_currency,
)
from hasta_la_vista_money.users.models import User


class Bank(models.Model):
    code = models.CharField(
        max_length=50,
        unique=True,
        verbose_name=_('Код банка'),
    )
    name = models.CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
        verbose_name=_('Название банка'),
    )
    is_system = models.BooleanField(
        default=False,
        verbose_name=_('Системный банк'),
    )
    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='personal_banks',
        verbose_name=_('Владелец'),
        help_text=_('Только для личных банков пользователя'),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Дата создания'),
    )

    class Meta:
        verbose_name = _('Банк')
        verbose_name_plural = _('Банки')
        ordering: ClassVar[list[str]] = ['name']
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=['name', 'user'],
                name='unique_bank_name_per_user',
                condition=Q(is_system=False),
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def natural_key(self) -> tuple[str]:
        return (self.code,)


def _get_default_bank_pk() -> int:
    return Bank.objects.get_or_create(
        code='-',
        defaults={'name': '—', 'is_system': True},
    )[0].pk


class AccountQuerySet(models.QuerySet['Account']):
    """
    Custom QuerySet for Account model with common filters.
    """

    def credit(self) -> 'AccountQuerySet':
        """Return only credit accounts and credit cards."""
        return self.filter(
            type_account__in=constants.CREDIT_ACCOUNT_TYPES,
        )

    def debit(self) -> 'AccountQuerySet':
        """Return only debit accounts, debit cards, and cash."""
        return self.filter(type_account__in=constants.LIQUID_ACCOUNT_TYPES)

    def by_user(self, user: 'User') -> 'AccountQuerySet':
        """Return accounts belonging to the given user."""
        return self.filter(user=user)

    def by_user_with_related(self, user: 'User') -> 'AccountQuerySet':
        """Return accounts belonging to the given user with
        select_related('user')."""
        return self.filter(user=user).select_related('user')

    def by_currency(self, currency: str) -> 'AccountQuerySet':
        """Return accounts with the specified currency code (e.g., 'RUB')."""
        return self.filter(currency=currency)

    def by_type(self, type_account: str) -> 'AccountQuerySet':
        """Return accounts of the specified type (e.g., 'CreditCard')."""
        return self.filter(type_account=type_account)

    def available_for_operations(self) -> 'AccountQuerySet':
        return self.filter(archived_at__isnull=True)


class AccountManager(models.Manager['Account']):
    """Keep deposit accounts behind the deposit domain service."""

    def get_queryset(self) -> AccountQuerySet:
        return AccountQuerySet(self.model, using=self._db)

    def credit(self) -> AccountQuerySet:
        return self.get_queryset().credit()

    def debit(self) -> AccountQuerySet:
        return self.get_queryset().debit()

    def by_user(self, user: User) -> AccountQuerySet:
        return self.get_queryset().by_user(user)

    def by_user_with_related(self, user: User) -> AccountQuerySet:
        return self.get_queryset().by_user_with_related(user)

    def by_currency(self, currency: str) -> AccountQuerySet:
        return self.get_queryset().by_currency(currency)

    def by_type(self, type_account: str) -> AccountQuerySet:
        return self.get_queryset().by_type(type_account)

    def available_for_operations(self) -> AccountQuerySet:
        return self.get_queryset().available_for_operations()

    def create(self, **kwargs: object) -> 'Account':
        if kwargs.get('type_account') == constants.ACCOUNT_TYPE_DEPOSIT:
            raise ValidationError(
                _('Счёт вклада можно создать только через сервис вкладов.'),
            )
        return super().create(**kwargs)

    def create_deposit(self, **kwargs: object) -> 'Account':
        kwargs['type_account'] = constants.ACCOUNT_TYPE_DEPOSIT
        return super().create(**kwargs)


class TimeStampedModel(models.Model):
    """
    Abstract base class with created_at and updated_at timestamps.
    """

    created_at = models.DateTimeField(
        auto_now_add=True,
        null=True,
        blank=True,
        verbose_name=_('Дата и время создания'),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        null=True,
        blank=True,
        verbose_name=_('Дата и время обновления'),
    )

    class Meta:
        abstract = True


class Account(TimeStampedModel):
    """
    Represents a user's financial account, which can be a credit/debit
    account, card, or cash.
    Stores balance, currency, type, and credit-related fields.
    Provides methods for money transfer and credit card debt calculations.
    """

    TYPE_ACCOUNT_LIST: ClassVar[list[tuple[str, str | Promise]]] = list(
        constants.ACCOUNT_TYPE_CHOICES,
    )

    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='finance_account_users',
    )
    name_account = models.CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
        default=_('Основной счёт'),
    )
    type_account = models.CharField(
        max_length=20,
        choices=TYPE_ACCOUNT_LIST,
        default=TYPE_ACCOUNT_LIST[1][0],
        verbose_name=_('Тип счёта'),
    )
    bank = models.ForeignKey(
        'Bank',
        on_delete=models.PROTECT,
        verbose_name=_('Банк'),
        help_text=_('Банк, выпустивший карту или обслуживающий счёт'),
        default=_get_default_bank_pk,
    )
    balance = models.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=2,
        default=0,
    )
    currency = models.CharField(
        max_length=3,
        choices=currency_choices('ru'),
        default=get_default_currency,
        verbose_name=_('Валюта'),
        help_text=_('Валюта счёта (например, {})').format(
            ', '.join([choice[1] for choice in currency_choices('ru')]),
        ),
    )
    limit_credit = models.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=2,
        default=0,
        verbose_name=_('Кредитный лимит'),
        null=True,
        blank=True,
        help_text=_('Только для кредитных карт и кредитных счетов'),
    )
    payment_due_date = models.DateField(
        verbose_name=_('Дата платежа'),
        null=True,
        blank=True,
        help_text=_('Только для кредитных карт и кредитных счетов'),
    )
    grace_period_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_('Длительность льготного периода (дней)'),
        help_text=_(
            'Для кредитных карт: сколько дней длится беспроцентный период '
            '(например, 120)',
        ),
    )
    archived_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_('Дата архивации'),
    )
    last_reconciled_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Дата последней сверки'),
    )

    objects = AccountManager()

    class Meta(TimeStampedModel.Meta):
        db_table = 'account'
        verbose_name = _('Счёт')
        verbose_name_plural = _('Счета')
        ordering: ClassVar[list[str]] = ['name_account']
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=['name_account']),
            models.Index(fields=['user']),
            models.Index(fields=['type_account']),
            models.Index(fields=['currency']),
        ]

    def __str__(self) -> str:
        """
        Returns the string representation of the account (its name).
        """
        return f'{self.name_account}'

    def get_absolute_url(self) -> str:
        """
        Returns the absolute URL to edit this account in the admin or UI.
        """
        return reverse('finance_account:change', args=[self.pk])

    @property
    def is_deposit(self) -> bool:
        return self.type_account == constants.ACCOUNT_TYPE_DEPOSIT

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None


class TransferMoneyLogQuerySet(models.QuerySet['TransferMoneyLog']):
    """
    Custom QuerySet for TransferMoneyLog model with common filters.
    """

    def by_user(self, user: 'User') -> 'TransferMoneyLogQuerySet':
        """Return transfer logs for the given user."""
        return self.filter(user=user)

    def by_date_range(
        self,
        start: date,
        end: date,
    ) -> 'TransferMoneyLogQuerySet':
        """Return transfer logs within the specified date range (inclusive)."""
        return self.filter(
            exchange_date__date__gte=start,
            exchange_date__date__lte=end,
        )


class TransferMoneyLogManager(models.Manager['TransferMoneyLog']):
    """
    Custom manager for TransferMoneyLog model, exposing common
    filters via QuerySet.
    """

    def get_queryset(self) -> TransferMoneyLogQuerySet:
        return TransferMoneyLogQuerySet(self.model, using=self._db)

    def by_user(self, user: 'User') -> TransferMoneyLogQuerySet:
        return self.get_queryset().by_user(user)

    def by_date_range(
        self,
        start: 'date',
        end: 'date',
    ) -> TransferMoneyLogQuerySet:
        return self.get_queryset().by_date_range(start, end)


class TransferMoneyLog(TimeStampedModel):
    """
    Stores logs of money transfers between accounts, including user,
    source, destination, amount, and notes.
    Used for auditing and tracking account movements.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='transfer_money',
    )
    from_account = models.ForeignKey(
        Account,
        related_name='from_account',
        on_delete=models.SET_NULL,
        null=True,
    )
    to_account = models.ForeignKey(
        Account,
        related_name='to_account',
        on_delete=models.SET_NULL,
        null=True,
    )
    amount = models.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
    )
    exchange_date = models.DateTimeField()
    notes = models.TextField(
        blank=True,
        verbose_name=_('Примечания'),
        help_text=_('Дополнительная информация о переводе'),
    )

    objects = TransferMoneyLogManager.from_queryset(TransferMoneyLogQuerySet)()

    class Meta(TimeStampedModel.Meta):
        verbose_name = _('Лог перевода денег')
        verbose_name_plural = _('Логи переводов денег')
        ordering: ClassVar[list[str]] = ['-exchange_date']
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=['user']),
            models.Index(fields=['from_account']),
            models.Index(fields=['to_account']),
            models.Index(fields=['exchange_date']),
        ]

    def __str__(self) -> str:
        """
        Returns a human-readable string describing the transfer log entry.
        """
        return str(
            _(
                '{date}. Перевод суммы {amount} со счёта '
                '"{from_account}" на счёт "{to_account}". ',
            ).format(
                date=self.exchange_date.strftime('%d-%m-%Y %H:%M'),
                amount=self.amount,
                from_account=self.from_account,
                to_account=self.to_account,
            ),
        )
