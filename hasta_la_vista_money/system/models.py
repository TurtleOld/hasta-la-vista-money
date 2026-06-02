"""System-level operational models."""

from typing import ClassVar

from django.db import models
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.users.models import User


class AuditLog(models.Model):
    """Immutable audit entry for financial model changes."""

    class Action(models.TextChoices):
        CREATE = 'create', _('Создание')
        UPDATE = 'update', _('Обновление')
        DELETE = 'delete', _('Удаление')

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        verbose_name=_('Пользователь'),
    )
    model_name = models.CharField(
        max_length=constants.ONE_HUNDRED,
        verbose_name=_('Модель'),
    )
    object_pk = models.CharField(
        max_length=constants.ONE_HUNDRED,
        verbose_name=_('ID объекта'),
    )
    object_name = models.CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
        blank=True,
        default='',
        verbose_name=_('Название объекта'),
    )
    action = models.CharField(
        max_length=constants.TWENTY,
        choices=Action.choices,
        verbose_name=_('Действие'),
    )
    diff = models.JSONField(default=dict, blank=True, verbose_name=_('Diff'))
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Дата создания'),
    )

    class Meta:
        verbose_name = _('Журнал аудита')
        verbose_name_plural = _('Журнал аудита')
        ordering: ClassVar[list[str]] = ['-created_at']
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['model_name', 'object_pk']),
            models.Index(fields=['action']),
        ]

    def __str__(self) -> str:
        return (
            f'{self.created_at:%Y-%m-%d %H:%M:%S} '
            f'{self.action} {self.model_name}#{self.object_pk}'
        )
