from datetime import date
from typing import ClassVar

from django.db import models
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money.expense.models import ExpenseCategory
from hasta_la_vista_money.income.models import IncomeCategory
from hasta_la_vista_money.users.models import User


class DateListQuerySet(models.QuerySet):
    def for_user(self, user: User) -> 'models.QuerySet[DateList]':
        """Filter date lists by user."""
        return self.filter(user=user)

    def for_date(self, target_date: date) -> 'models.QuerySet[DateList]':
        """Filter date lists by date."""
        return self.filter(date=target_date)


class DateListManager(models.Manager):
    def get_queryset(self) -> DateListQuerySet:
        return DateListQuerySet(self.model, using=self._db)

    def for_user(self, user: User) -> DateListQuerySet:
        return self.get_queryset().for_user(user)

    def for_date(self, target_date: date) -> DateListQuerySet:
        return self.get_queryset().for_date(target_date)


class DateList(models.Model):
    """
    Stores a list of dates for a user, used for budget planning.
    """

    user: User = models.ForeignKey(
        'users.User',
        on_delete=models.CASCADE,
        related_name='budget_date_lists',
        verbose_name=_('Пользователь'),
        help_text=_('Пользователь, для которого ведется список дат'),
    )
    date: date = models.DateField(
        default=date.today,
        verbose_name=_('Дата'),
        help_text=_('Дата планирования'),
        db_index=True,
    )
    created_at: date = models.DateTimeField(
        auto_now_add=True,
        null=True,
        blank=True,
        verbose_name=_('Дата создания'),
        help_text=_('Когда запись была создана'),
    )

    objects = DateListManager()

    class Meta:
        verbose_name = _('Список дат')
        verbose_name_plural = _('Списки дат')
        ordering: ClassVar[list[str]] = ['-date']
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=['user', 'date']),
        ]

    def __str__(self) -> str:
        return f'{self.user} - {self.date}'


class PlanningQuerySet(models.QuerySet):
    def expenses(self) -> 'models.QuerySet[Planning]':
        """Filter only expense plans."""
        return self.filter(type=Planning.Type.EXPENSE)

    def incomes(self) -> 'models.QuerySet[Planning]':
        """Filter only income plans."""
        return self.filter(type=Planning.Type.INCOME)

    def for_user(self, user: User) -> 'models.QuerySet[Planning]':
        return self.filter(user=user)

    def for_period(self, start: date, end: date) -> 'models.QuerySet[Planning]':
        return self.filter(date__range=(start, end))

    def with_related(self) -> 'models.QuerySet[Planning]':
        """Optimize queries by joining related categories."""
        return self.select_related(
            'user',
            'category_expense',
            'category_income',
        )


class PlanningManager(models.Manager):
    def get_queryset(self) -> PlanningQuerySet:
        return PlanningQuerySet(self.model, using=self._db).with_related()

    def expenses(self) -> PlanningQuerySet:
        return self.get_queryset().expenses()

    def incomes(self) -> PlanningQuerySet:
        return self.get_queryset().incomes()

    def for_user(self, user: User) -> PlanningQuerySet:
        return self.get_queryset().for_user(user)

    def for_period(self, start: date, end: date) -> PlanningQuerySet:
        return self.get_queryset().for_period(start, end)


class Planning(models.Model):
    """
    Stores a planned budget item (expense or income) for a user and category.
    """

    class Type(models.TextChoices):
        EXPENSE = 'expense', _('Расход')
        INCOME = 'income', _('Доход')

    user: User = models.ForeignKey(
        'users.User',
        on_delete=models.CASCADE,
        related_name='plannings',
        verbose_name=_('Пользователь'),
        help_text=_('Пользователь, для которого ведется планирование'),
        db_index=True,
    )
    category_expense: ExpenseCategory = models.ForeignKey(
        'expense.ExpenseCategory',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='plannings_expense',
        verbose_name=_('Категория расхода'),
        help_text=_('Категория расхода (если применимо)'),
    )
    category_income: IncomeCategory = models.ForeignKey(
        'income.IncomeCategory',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='plannings_income',
        verbose_name=_('Категория дохода'),
        help_text=_('Категория дохода (если применимо)'),
    )
    date: date = models.DateField(
        default=date.today,
        verbose_name=_('Дата'),
        help_text=_('Дата планирования'),
        db_index=True,
    )
    amount: float = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name=_('Сумма'),
        help_text=_('Планируемая сумма'),
    )
    type: str = models.CharField(
        max_length=10,
        choices=Type.choices,
        default=Type.EXPENSE,
        verbose_name=_('Тип'),
        help_text=_('Тип планирования: расход или доход'),
        db_index=True,
    )
    created_at: date = models.DateTimeField(
        auto_now_add=True,
        null=True,
        blank=True,
        verbose_name=_('Дата создания'),
        help_text=_('Когда запись была создана'),
    )

    objects = PlanningManager()

    class Meta:
        verbose_name = _('Планирование')
        verbose_name_plural = _('Планирования')
        ordering: ClassVar[list[str]] = ['-date']
        constraints: ClassVar[list[models.UniqueConstraint]] = [
            models.UniqueConstraint(
                fields=[
                    'user',
                    'category_expense',
                    'category_income',
                    'date',
                    'type',
                ],
                name='unique_planning_per_user_category_date_type',
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=['user', 'date', 'type']),
        ]

    def __str__(self) -> str:
        return f'{self.user} - {self.date} - {self.type} - {self.amount}'

    def is_expense(self) -> bool:
        """Return True if this planning is for an expense."""
        return self.type == self.Type.EXPENSE

    def is_income(self) -> bool:
        """Return True if this planning is for an income."""
        return self.type == self.Type.INCOME
