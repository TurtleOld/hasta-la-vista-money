"""Django models for unified financial transactions.

The :class:`Transaction` model replaces the previously separate ``Income``
and ``Expense`` models, using a ``type`` discriminator. The :class:`Category`
model replaces ``IncomeCategory`` and ``ExpenseCategory`` in the same way.
"""

from decimal import Decimal
from typing import ClassVar

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.managers import TransactionQuerySet
from hasta_la_vista_money.users.models import User


class TransactionType(models.TextChoices):
    """Discriminator distinguishing income and expense rows."""

    INCOME = 'income', _('Доход')
    EXPENSE = 'expense', _('Расход')


TransactionManager = models.Manager.from_queryset(TransactionQuerySet)


class Category(models.Model):
    """Unified category model with a type discriminator.

    Categories can be hierarchical via ``parent_category``. The ``(user,
    name, type)`` tuple is unique, allowing a user to reuse the same name
    across income and expense categories.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='categories',
    )
    name = models.CharField(max_length=constants.TWO_HUNDRED_FIFTY)
    type = models.CharField(
        max_length=10,
        choices=TransactionType.choices,
    )
    parent_category = models.ForeignKey(
        'self',
        blank=True,
        null=True,
        related_name='subcategories',
        on_delete=models.PROTECT,
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    class Meta:
        ordering: ClassVar[list[str]] = ['name']
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=['name']),
            models.Index(fields=['user', 'type']),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=['user', 'name', 'type'],
                name='unique_user_category_per_type',
            ),
        ]

    def __str__(self) -> str:
        """Return the category name."""
        return str(self.name)


class Transaction(models.Model):
    """Unified financial transaction model.

    ``type`` distinguishes incomes from expenses. The pair
    ``(transaction.type, transaction.category.type)`` is expected to match;
    this invariant is enforced by forms and services rather than by the
    database to keep migrations simple.
    """

    type = models.CharField(
        max_length=10,
        choices=TransactionType.choices,
    )
    date = models.DateTimeField()
    amount = models.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        null=True,
        blank=True,
        verbose_name=_('Дата создания'),
    )
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='transactions',
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='transactions',
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='transactions',
    )

    objects = TransactionManager()

    class Meta:
        ordering: ClassVar[list[str]] = ['-date']
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=['-date']),
            models.Index(fields=['amount']),
            models.Index(fields=['user', 'date']),
            models.Index(fields=['user', 'type', 'date']),
            models.Index(fields=['user', 'category']),
            models.Index(fields=['user', 'account']),
            models.Index(fields=['date', 'amount']),
        ]

    def __str__(self) -> str:
        """Return the related category name for display."""
        return str(self.category)
