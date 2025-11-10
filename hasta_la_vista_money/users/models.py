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
    theme: CharField[Any, Any] = CharField(max_length=10, default='dark')

    def __str__(self) -> str:
        return str(self.username)


class DashboardWidget(Model):
    """Модель для хранения пользовательских настроек виджетов дашборда."""

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
        return f'{self.user.username} - {self.widget_type}'


class TokenAdmin(admin.ModelAdmin[Any]):
    search_fields = ('key', 'user__username')
