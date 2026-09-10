"""System-level operational models."""

from typing import ClassVar

from django.db import models
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.users.models import User


class AuditOperationKind(models.TextChoices):
    """Closed list of user operations the audit history can name.

    Assigned by ``audit_operation(kind=...)`` around a unit of work; the
    write layer only stores whatever the caller passes. Wiring each call
    site to the kind it belongs to is a separate ticket.
    """

    TRANSFER = 'transfer', _('Перевод')
    RECEIPT_PURCHASE = 'receipt_purchase', _('Чек')
    INCOME = 'income', _('Доход')
    EXPENSE = 'expense', _('Расход')
    TRANSACTION_EDIT = 'transaction_edit', _('Правка транзакции')
    TRANSACTION_DELETE = 'transaction_delete', _('Удаление транзакции')
    RECEIPT_EDIT = 'receipt_edit', _('Правка чека')
    RECEIPT_DELETE = 'receipt_delete', _('Удаление чека')
    ACCOUNT_EDIT = 'account_edit', _('Правка счёта')
    ACCOUNT_DELETE = 'account_delete', _('Удаление счёта')
    STATEMENT_IMPORT = 'statement_import', _('Импорт выписки')
    STATEMENT_IMPORT_RESOLUTION = (
        'statement_import_resolution',
        _('Разбор нерешённых строк'),
    )


class AuditLog(models.Model):
    """Immutable audit entry for financial model changes."""

    class Action(models.TextChoices):
        CREATE = 'create', _('Создание')
        UPDATE = 'update', _('Обновление')
        DELETE = 'delete', _('Удаление')

    operation_id = models.UUIDField(
        null=True,
        blank=True,
        verbose_name=_('Идентификатор операции'),
    )
    kind = models.CharField(
        max_length=constants.THIRTY,
        choices=AuditOperationKind.choices,
        null=True,
        blank=True,
        verbose_name=_('Вид операции'),
    )
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
        ordering: ClassVar[list[str]] = ['-created_at', '-id']
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['model_name', 'object_pk']),
            models.Index(fields=['action']),
            models.Index(fields=['operation_id']),
        ]

    def __str__(self) -> str:
        return (
            f'{self.created_at:%Y-%m-%d %H:%M:%S} '
            f'{self.action} {self.model_name}#{self.object_pk}'
        )
