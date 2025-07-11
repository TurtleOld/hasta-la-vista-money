from decimal import Decimal

from django.db import models
from django.db.models import Sum
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
    TYPE_ACCOUNT_LIST = [
        ('Credit', _('Кредитный счёт')),
        ('Debit', _('Дебетовый счёт')),
        ('CreditCard', _('Кредитная карта')),
        ('DebitCard', _('Дебетовая карта')),
        ('CASH', _('Наличные')),
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
        choices=TYPE_ACCOUNT_LIST,
        default=TYPE_ACCOUNT_LIST[1][0],
        verbose_name=_('Тип счёта'),
    )
    balance = models.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=2,
        default=0,
    )
    currency = models.CharField(choices=CURRENCY_LIST)
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
            'Для кредитных карт: сколько дней длится беспроцентный период (например, 120)',
        ),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        null=True,
        blank=True,
        verbose_name=_('Дата и время создания'),
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

    def get_credit_card_debt(self, start_date=None, end_date=None):
        """
        Возвращает сумму долга по кредитной карте (или кредитному счёту) за указанный период.
        Если период не указан — считает на текущий момент.
        Учитывает:
        - Expense (расходы) — увеличивают долг
        - Income (доходы) — уменьшают долг
        - Receipt (operation_type=1 — покупка, увеличивает долг; operation_type=2 — возврат, уменьшает долг)
        """
        from datetime import date, datetime, time

        from hasta_la_vista_money.expense.models import Expense
        from hasta_la_vista_money.income.models import Income
        from hasta_la_vista_money.receipts.models import Receipt

        # Только для кредитных карт и кредитных счетов
        if self.type_account not in ('CreditCard', 'Credit'):
            return None

        expense_qs = Expense.objects.filter(account=self)
        income_qs = Income.objects.filter(account=self)
        receipt_qs = Receipt.objects.filter(account=self)

        if start_date and end_date:
            # start_date может быть date или datetime
            if isinstance(start_date, date) and not isinstance(start_date, datetime):
                start_dt = datetime.combine(start_date, time.min)
            else:
                start_dt = start_date
            if isinstance(end_date, date) and not isinstance(end_date, datetime):
                end_dt = datetime.combine(end_date, time.max)
            else:
                end_dt = end_date
            expense_qs = expense_qs.filter(date__range=(start_dt, end_dt))
            income_qs = income_qs.filter(date__range=(start_dt, end_dt))
            receipt_qs = receipt_qs.filter(receipt_date__range=(start_dt, end_dt))

        total_expense = expense_qs.aggregate(total=Sum('amount'))['total'] or 0
        total_income = income_qs.aggregate(total=Sum('amount'))['total'] or 0
        total_receipt_expense = (
            receipt_qs.filter(operation_type=1).aggregate(total=Sum('total_sum'))[
                'total'
            ]
            or 0
        )
        total_receipt_return = (
            receipt_qs.filter(operation_type=2).aggregate(total=Sum('total_sum'))[
                'total'
            ]
            or 0
        )

        debt = (total_expense + total_receipt_expense) - (
            total_income + total_receipt_return
        )
        return debt

    def calculate_grace_period_info(self, purchase_month):
        """
        Рассчитывает информацию о беспроцентном периоде для кредитной карты.

        Логика: 1 месяц на покупки + 3 месяца на погашение
        Например: покупки в мае -> погашение до конца августа
        """
        from calendar import monthrange
        from datetime import datetime, time

        from dateutil.relativedelta import relativedelta
        from django.utils import timezone

        # Начало месяца покупок
        purchase_start = purchase_month.replace(day=1)

        # Конец месяца покупок (23:59:59)
        last_day = monthrange(purchase_start.year, purchase_start.month)[1]
        purchase_end = datetime.combine(purchase_start.replace(day=last_day), time.max)

        # Конец беспроцентного периода (3 месяца после месяца покупок, 23:59:59)
        grace_end_date = purchase_start + relativedelta(months=3)
        last_day_grace = monthrange(grace_end_date.year, grace_end_date.month)[1]
        grace_end = datetime.combine(
            grace_end_date.replace(day=last_day_grace),
            time.max,
        )

        # Рассчитываем долг за месяц покупок
        debt_for_month = self.get_credit_card_debt(purchase_start, purchase_end)

        # Рассчитываем платежи за период погашения
        payments_start = purchase_end + relativedelta(seconds=1)
        payments_end = grace_end
        payments_for_period = self.get_credit_card_debt(payments_start, payments_end)

        # Итоговый долг после беспроцентного периода
        final_debt = (debt_for_month or 0) + (payments_for_period or 0)

        return {
            'purchase_month': purchase_start.strftime('%m.%Y'),
            'purchase_start': purchase_start,
            'purchase_end': purchase_end,
            'grace_end': grace_end,
            'debt_for_month': debt_for_month,
            'payments_for_period': payments_for_period,
            'final_debt': final_debt,
            'is_overdue': timezone.now() > grace_end and final_debt > 0,
            'days_until_due': (grace_end.date() - timezone.now().date()).days
            if timezone.now() <= grace_end
            else 0,
        }


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
