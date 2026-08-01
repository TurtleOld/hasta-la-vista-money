"""Django models for user management.

This module contains models for users and user-related features,
including dashboard widgets and admin configurations.
"""

from typing import Any

from django.contrib import admin
from django.contrib.auth.models import AbstractUser, Group
from django.db.models import (
    CASCADE,
    SET_NULL,
    BooleanField,
    CharField,
    DateTimeField,
    DecimalField,
    FileField,
    ForeignKey,
    Index,
    IntegerField,
    JSONField,
    Model,
    PositiveIntegerField,
    Q,
    TextChoices,
    TextField,
    UniqueConstraint,
)
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """Extended user model with theme support.

    Extends Django's AbstractUser to add theme preference
    for the user interface.

    Attributes:
        theme: User's preferred theme (default: 'auto').
    """

    theme: CharField[Any, Any] = CharField(max_length=10, default='auto')

    def __str__(self) -> str:
        """Return string representation of the user.

        Returns:
            str: The username.
        """
        return str(self.username)


class DashboardWidget(Model):
    """Model for storing user dashboard widget settings.

    Stores configuration for dashboard widgets including position,
    size, visibility, and custom configuration data.

    Attributes:
        user: Foreign key to the User who owns this widget.
        widget_type: Type identifier of the widget.
        position: Position order of the widget on the dashboard.
        width: Width of the widget in grid units.
        height: Height of the widget in pixels.
        config: JSON field for widget-specific configuration.
        is_visible: Whether the widget is currently visible.
        created_at: Timestamp when the widget was created.
        updated_at: Timestamp when the widget was last updated.
    """

    user = ForeignKey(User, on_delete=CASCADE, related_name='dashboard_widgets')
    widget_type = CharField(max_length=50)
    position = PositiveIntegerField(default=0)
    width = PositiveIntegerField(default=6)
    height = PositiveIntegerField(default=300)
    config = JSONField(default=dict)
    is_visible = BooleanField(default=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        ordering = ['position', 'created_at']
        verbose_name = _('Виджет дашборда')
        verbose_name_plural = _('Виджеты дашборда')

    def __str__(self) -> str:
        """Return string representation of the widget.

        Returns:
            str: Formatted string with username and widget type.
        """
        return f'{self.user.username} - {self.widget_type}'


class BankStatementUpload(Model):
    """Model for tracking bank statement upload and processing status.

    Attributes:
        user: Foreign key to the User who uploaded the statement.
        account: Foreign key to the Account associated with the statement.
        pdf_file: Path to the uploaded PDF file.
        status: Current processing status (pending, processing, completed,
            failed).
        progress: Progress percentage (0-100).
        total_transactions: Total number of transactions found.
        processed_transactions: Number of transactions processed so far.
        income_count: Number of income transactions created.
        expense_count: Number of expense transactions created.
        error_message: Error message if processing failed.
        celery_task_id: Celery task ID for tracking.
        created_at: Timestamp when the upload was created.
        updated_at: Timestamp when the upload was last updated.
    """

    class Status(TextChoices):
        PENDING = 'pending', _('В очереди')
        PROCESSING = 'processing', _('Обрабатывается')
        AWAITING_CONFIRMATION = (
            'awaiting_confirmation',
            _('Ожидает подтверждения'),
        )
        COMPLETED = 'completed', _('Завершено')
        FAILED = 'failed', _('Ошибка')

    user = ForeignKey(
        User,
        on_delete=CASCADE,
        related_name='bank_statement_uploads',
    )
    account = ForeignKey('finance_account.Account', on_delete=CASCADE)
    pdf_file = FileField(upload_to='bank_statements/')
    file_hash = CharField(max_length=64, blank=True, default='')
    status = CharField(
        max_length=21,
        choices=Status.choices,
        default=Status.PENDING,
    )
    progress = IntegerField(default=0)
    total_transactions = IntegerField(default=0)
    processed_transactions = IntegerField(default=0)
    income_count = IntegerField(default=0)
    expense_count = IntegerField(default=0)
    skipped_count = IntegerField(default=0)
    imported_count = IntegerField(default=0)
    linked_count = IntegerField(default=0)
    awaiting_decision_count = IntegerField(default=0)
    expired_count = IntegerField(default=0)
    failed_count = IntegerField(default=0)
    statement_closing_balance = DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_('Остаток по выписке'),
    )
    account_balance_after = DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_('Остаток в приложении после импорта'),
    )
    balance_discrepancy = DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_('Расхождение баланса'),
    )
    error_message = TextField(blank=True, default='')
    celery_task_id = CharField(max_length=255, blank=True, default='')
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _('Загрузка банковской выписки')
        verbose_name_plural = _('Загрузки банковских выписок')
        constraints = [
            UniqueConstraint(
                fields=['account', 'file_hash'],
                condition=~Q(file_hash=''),
                name='uniq_statement_account_file_hash',
            ),
        ]

    def __str__(self) -> str:
        """Return string representation of the upload.

        Returns:
            str: Formatted string with username and status.
        """
        return f'{self.user.username} - {self.status} - {self.created_at}'


class BankStatementRow(Model):
    """Parsed statement row awaiting a reconciliation decision."""

    class Decision(TextChoices):
        PENDING = 'pending', _('Ожидает решения')
        LINKED = 'linked', _('Уже учтена')
        NEW = 'new', _('Новая операция')

    class TransactionType(TextChoices):
        INCOME = 'income', _('Доход')
        EXPENSE = 'expense', _('Расход')

    upload = ForeignKey(
        BankStatementUpload,
        on_delete=CASCADE,
        related_name='statement_rows',
    )
    transaction_type = CharField(
        max_length=10,
        choices=TransactionType.choices,
    )
    transaction_date = DateTimeField()
    amount = DecimalField(max_digits=20, decimal_places=2)
    description = CharField(max_length=250)
    candidate_description = CharField(max_length=250)
    suggested_category = CharField(max_length=250)
    source_ref = CharField(max_length=64, blank=True, null=True)
    source_row_position = PositiveIntegerField()
    match_calendar_date = BooleanField(default=False)
    candidate = ForeignKey(
        'transactions.Transaction',
        on_delete=SET_NULL,
        related_name='statement_candidates',
        blank=True,
        null=True,
    )
    transaction = ForeignKey(
        'transactions.Transaction',
        on_delete=CASCADE,
        related_name='statement_rows',
        blank=True,
        null=True,
    )
    decision = CharField(
        max_length=10,
        choices=Decision.choices,
        default=Decision.PENDING,
    )
    created_at = DateTimeField(auto_now_add=True)
    decided_at = DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['transaction_date', 'pk']
        constraints = [
            UniqueConstraint(
                fields=['upload', 'source_row_position'],
                name='unique_statement_upload_row',
            ),
        ]
        indexes = [
            Index(
                fields=['upload', 'decision'],
                name='users_statement_decision_idx',
            ),
        ]


class BankStatementCandidate(Model):
    """Financial movement matching a statement row."""

    row = ForeignKey(
        BankStatementRow,
        on_delete=CASCADE,
        related_name='candidates',
    )
    transaction = ForeignKey(
        'transactions.Transaction',
        on_delete=SET_NULL,
        related_name='statement_candidate_links',
        blank=True,
        null=True,
    )
    description = CharField(max_length=250)
    rank = PositiveIntegerField(default=0)

    class Meta:
        ordering = ['rank', 'pk']
        constraints = [
            UniqueConstraint(
                fields=['row', 'transaction'],
                name='unique_statement_row_candidate',
            ),
        ]


class FamilyGroupMembership(Model):
    """User role inside a shared family finance group."""

    class Role(TextChoices):
        OWNER = 'owner', _('Владелец')
        VIEWER = 'viewer', _('Просмотр')

    group = ForeignKey(
        Group,
        on_delete=CASCADE,
        related_name='family_memberships',
    )
    user = ForeignKey(
        User,
        on_delete=CASCADE,
        related_name='family_memberships',
    )
    role = CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.VIEWER,
    )
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=['group', 'user'],
                name='unique_family_group_membership',
            ),
        ]
        verbose_name = _('Участник семейной группы')
        verbose_name_plural = _('Участники семейных групп')

    def __str__(self) -> str:
        return f'{self.group.name}: {self.user.username} ({self.role})'


class FamilyInvite(Model):
    """Share link for joining a family finance group."""

    group = ForeignKey(
        Group,
        on_delete=CASCADE,
        related_name='family_invites',
    )
    created_by = ForeignKey(
        User,
        on_delete=CASCADE,
        related_name='created_family_invites',
    )
    token = CharField(max_length=64, unique=True)
    role = CharField(
        max_length=20,
        choices=FamilyGroupMembership.Role.choices,
        default=FamilyGroupMembership.Role.VIEWER,
    )
    is_active = BooleanField(default=True)
    expires_at = DateTimeField(null=True, blank=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    def is_expired(self) -> bool:
        """Return True if the invite has passed its expiry date."""
        return self.expires_at is not None and timezone.now() > self.expires_at

    class Meta:
        ordering = ['-created_at']
        verbose_name = _('Семейное приглашение')
        verbose_name_plural = _('Семейные приглашения')

    def __str__(self) -> str:
        return f'{self.group.name}: {self.role}'


class TokenAdmin(admin.ModelAdmin[Any]):
    """Admin configuration for token model.

    Provides search functionality for tokens by key and username.
    """

    search_fields = ('key', 'user__username')
