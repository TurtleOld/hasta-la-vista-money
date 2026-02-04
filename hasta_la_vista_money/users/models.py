"""Django models for user management.

This module contains models for users and user-related features,
including dashboard widgets and admin configurations.
"""

from typing import Any

from django.contrib import admin
from django.contrib.auth.models import AbstractUser
from django.db.models import (
    CASCADE,
    BooleanField,
    CharField,
    DateTimeField,
    FileField,
    ForeignKey,
    IntegerField,
    JSONField,
    Model,
    PositiveIntegerField,
    TextField,
)
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """Extended user model with theme support.

    Extends Django's AbstractUser to add theme preference
    for the user interface.

    Attributes:
        theme: User's preferred theme (default: 'dark').
    """

    theme: CharField[Any, Any] = CharField(max_length=10, default='dark')

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

    STATUS_CHOICES = [
        ('pending', _('В очереди')),
        ('processing', _('Обрабатывается')),
        ('completed', _('Завершено')),
        ('failed', _('Ошибка')),
    ]

    user = ForeignKey(
        User,
        on_delete=CASCADE,
        related_name='bank_statement_uploads',
    )
    account = ForeignKey('finance_account.Account', on_delete=CASCADE)
    pdf_file = FileField(upload_to='bank_statements/')
    status = CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    progress = IntegerField(default=0)
    total_transactions = IntegerField(default=0)
    processed_transactions = IntegerField(default=0)
    income_count = IntegerField(default=0)
    expense_count = IntegerField(default=0)
    error_message = TextField(blank=True, default='')
    celery_task_id = CharField(max_length=255, blank=True, default='')
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _('Загрузка банковской выписки')
        verbose_name_plural = _('Загрузки банковских выписок')

    def __str__(self) -> str:
        """Return string representation of the upload.

        Returns:
            str: Formatted string with username and status.
        """
        return f'{self.user.username} - {self.status} - {self.created_at}'


class TokenAdmin(admin.ModelAdmin[Any]):
    """Admin configuration for token model.

    Provides search functionality for tokens by key and username.
    """

    search_fields = ('key', 'user__username')
