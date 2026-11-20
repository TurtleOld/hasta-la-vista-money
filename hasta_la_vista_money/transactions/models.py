"""Django models for unified financial transactions.

The :class:`Transaction` model replaces the previously separate ``Income``
and ``Expense`` models, using a ``type`` discriminator. The :class:`Category`
model replaces ``IncomeCategory`` and ``ExpenseCategory`` in the same way.
"""

from decimal import Decimal
from typing import TYPE_CHECKING, ClassVar

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from django_stubs_ext.db.models.manager import RelatedManager

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.managers import TransactionQuerySet
from hasta_la_vista_money.users.models import User


class TransactionType(models.TextChoices):
    """Discriminator distinguishing income and expense rows."""

    INCOME = 'income', _('Доход')
    EXPENSE = 'expense', _('Расход')


class SystemCategoryKind(models.TextChoices):
    """Kinds of protected system categories (empty value: regular)."""

    BALANCE_ADJUSTMENT = 'balance_adjustment', _('Корректировка остатка')


TransactionManager = models.Manager.from_queryset(TransactionQuerySet)


class Category(models.Model):
    """Unified category model with a type discriminator.

    Categories can be hierarchical via ``parent_category``. The ``(user,
    name, type)`` tuple is unique, allowing a user to reuse the same name
    across income and expense categories.
    """

    if TYPE_CHECKING:
        id: int
        user_id: int
        parent_category_id: int | None
        subcategories: RelatedManager['Category']

        def get_type_display(self) -> str: ...

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
    system_kind = models.CharField(
        max_length=32,
        choices=SystemCategoryKind.choices,
        blank=True,
        default='',
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
            models.UniqueConstraint(
                fields=['user', 'system_kind', 'type'],
                condition=~Q(system_kind=''),
                name='unique_user_system_category_kind_per_type',
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

    if TYPE_CHECKING:
        user_id: int
        account_id: int
        category_id: int

    type = models.CharField(
        max_length=10,
        choices=TransactionType.choices,
    )
    date = models.DateTimeField()
    bank_calendar_date = models.DateField(blank=True, null=True)
    amount = models.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    description = models.CharField(max_length=250, blank=True, default='')
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
    source_ref = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        verbose_name=_('Идентификатор операции в выписке'),
    )
    source_file_hash = models.CharField(
        max_length=64,
        blank=True,
        null=True,
    )
    source_row_position = models.PositiveIntegerField(
        blank=True,
        null=True,
    )
    source_ref_hash = models.CharField(
        max_length=64,
        blank=True,
        null=True,
    )
    source_ref_key_id = models.CharField(max_length=64, blank=True, default='')
    source_ref_version = models.PositiveSmallIntegerField(default=1)
    source_identity_trusted = models.BooleanField(default=False)

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
            models.Index(fields=['account', 'source_ref']),
            models.Index(
                fields=['account', 'source_file_hash', 'source_row_position'],
            ),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=['account', 'source_ref'],
                condition=Q(source_ref__isnull=False),
                name='unique_account_source_ref',
            ),
            models.UniqueConstraint(
                fields=['account', 'source_ref_hash'],
                condition=Q(
                    source_ref_hash__isnull=False,
                    source_identity_trusted=True,
                ),
                name='unique_account_source_ref_hash',
            ),
            models.UniqueConstraint(
                fields=[
                    'account',
                    'source_file_hash',
                    'source_row_position',
                ],
                condition=Q(source_file_hash__isnull=False),
                name='unique_statement_source_row',
            ),
        ]

    def __str__(self) -> str:
        """Return the related category name for display."""
        return str(self.category)
