from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar

from django.db import models
from django.urls import reverse
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.constants import (
    ACCOUNT_TYPE_CREDIT,
    ACCOUNT_TYPE_CREDIT_CARD,
)
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.services import (
        GracePeriodInfoDict,
    )


class AccountQuerySet(models.QuerySet['Account']):
    """
    Custom QuerySet for Account model with common filters.
    """

    def credit(self) -> 'AccountQuerySet':
        """Return only credit accounts and credit cards."""
        return self.filter(
            type_account__in=[ACCOUNT_TYPE_CREDIT, ACCOUNT_TYPE_CREDIT_CARD],
        )

    def debit(self) -> 'AccountQuerySet':
        """Return only debit accounts, debit cards, and cash."""
        return self.filter(type_account__in=['Debit', 'DebitCard', 'CASH'])

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


class AccountManager(models.Manager['Account']):
    """
    Custom manager for Account model, exposing common filters via QuerySet.
    """

    def get_queryset(self) -> AccountQuerySet:
        return AccountQuerySet(self.model, using=self._db)

    def credit(self) -> AccountQuerySet:
        """Shortcut for Account.objects.credit()."""
        return self.get_queryset().credit()

    def debit(self) -> AccountQuerySet:
        """Shortcut for Account.objects.debit()."""
        return self.get_queryset().debit()

    def by_user(self, user: 'User') -> AccountQuerySet:
        return self.get_queryset().by_user(user)

    def by_user_with_related(self, user: 'User') -> AccountQuerySet:
        return self.get_queryset().by_user_with_related(user)

    def by_currency(self, currency: str) -> AccountQuerySet:
        return self.get_queryset().by_currency(currency)

    def by_type(self, type_account: str) -> AccountQuerySet:
        return self.get_queryset().by_type(type_account)


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

    CURRENCY_LIST: ClassVar[list[tuple[str, str | Promise]]] = [
        ('RUB', _('Российский рубль')),
        ('USD', _('Доллар США')),
        ('EUR', _('Евро')),
        ('GBP', _('Британский фунт')),
        ('CZK', _('Чешская крона')),
        ('PLN', _('Польский злотый')),
        ('TRY', _('Турецкая лира')),
        ('CNH', _('Китайский юань')),
    ]
    TYPE_ACCOUNT_LIST: ClassVar[list[tuple[str, str | Promise]]] = [
        ('Credit', _('Кредитный счёт')),
        ('Debit', _('Дебетовый счёт')),
        ('CreditCard', _('Кредитная карта')),
        ('DebitCard', _('Дебетовая карта')),
        ('CASH', _('Наличные')),
    ]
    BANK_LIST: ClassVar[list[tuple[str, str | Promise]]] = [
        ('-', _('—')),  # Default value - dash
        ('SBERBANK', _('Сбербанк')),
        ('RAIFFAISENBANK', _('Райффайзенбанк')),
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
    type_account = models.CharField(
        max_length=20,
        choices=TYPE_ACCOUNT_LIST,
        default=TYPE_ACCOUNT_LIST[1][0],
        verbose_name=_('Тип счёта'),
    )
    bank = models.CharField(
        max_length=20,
        choices=BANK_LIST,
        default='-',
        verbose_name=_('Банк'),
        help_text=_('Банк, выпустивший карту или обслуживающий счёт'),
    )
    balance = models.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=2,
        default=0,
    )
    currency = models.CharField(
        max_length=10,
        choices=CURRENCY_LIST,
        default='RUB',
        verbose_name=_('Валюта'),
        help_text=_('Валюта счёта (например, RUB, USD)'),
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

    objects = AccountManager.from_queryset(AccountQuerySet)()

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

    def transfer_money(self, to_account: 'Account', amount: Decimal) -> bool:
        """
        Transfers a specified amount of money from this account to another
        account.
        Returns True if the transfer was successful, False otherwise
        (e.g., insufficient funds).

        Args:
            to_account (Account): The account to transfer money to.
            amount (Decimal): The amount to transfer.

        Returns:
            bool: True if transfer succeeded, False otherwise.
        """
        if amount <= 0:
            return False
        if amount <= self.balance:
            self.balance -= amount
            to_account.balance += amount
            self.save()
            to_account.save()
            return True
        return False

    def get_credit_card_debt(
        self,
        start_date: Any | None = None,
        end_date: Any | None = None,
    ) -> Decimal | None:
        """
        Calculates the credit card (or credit account) debt for a given period.
        If no period is specified, calculates the current debt.
        Considers expenses, incomes, and receipts (purchases and returns).

        Args:
            start_date (date|datetime|None): Start of the period (inclusive).
            end_date (date|datetime|None): End of the period (inclusive).

        Returns:
            Optional[Decimal]: The calculated debt, or None if not a credit
            account.
        """
        from hasta_la_vista_money.finance_account.services import (
            AccountService,
        )

        return AccountService.get_credit_card_debt(
            account=self,
            start_date=start_date,
            end_date=end_date,
        )

    def calculate_grace_period_info(
        self,
        purchase_month: Any,
    ) -> 'GracePeriodInfoDict':
        """
        Calculates grace period information for a credit card.
        Logic: 1 month for purchases + 3 months for repayment.
        Example: purchases in May -> repayment due by end of August.

        Args:
            purchase_month (date|datetime): The month of purchases
            (first day of month).

        Returns:
            dict: Information about the grace period, including dates,
            debts, and overdue status.
        """
        from hasta_la_vista_money.finance_account.services import (
            AccountService,
        )

        return AccountService.calculate_grace_period_info(
            account=self,
            purchase_month=purchase_month,
        )


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
