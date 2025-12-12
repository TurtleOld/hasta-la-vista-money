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
    ForeignKey,
    JSONField,
    Model,
    PositiveIntegerField,
)


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
        verbose_name = 'Виджет дашборда'
        verbose_name_plural = 'Виджеты дашборда'

    def __str__(self) -> str:
        """Return string representation of the widget.

        Returns:
            str: Formatted string with username and widget type.
        """
        return f'{self.user.username} - {self.widget_type}'


class TokenAdmin(admin.ModelAdmin[Any]):
    """Admin configuration for token model.

    Provides search functionality for tokens by key and username.
    """

    search_fields = ('key', 'user__username')
