"""Serializers for finance account models.

This module provides Django REST Framework serializers for converting
finance account models to and from JSON format for API communication.
"""

from typing import Any, ClassVar

from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from hasta_la_vista_money.finance_account.models import Account


class AccountSerializer(serializers.ModelSerializer[Account]):
    """Serializer for Account model.

    Converts Account model instances to JSON format for API responses,
    including essential account information like name, balance, and currency.
    """

    type_account_display = serializers.CharField(
        source='get_type_account_display',
        read_only=True,
    )
    user_username = serializers.CharField(
        source='user.username',
        read_only=True,
    )
    url = serializers.SerializerMethodField()
    delete_url = serializers.SerializerMethodField()
    is_foreign = serializers.SerializerMethodField()

    class Meta:
        model = Account
        fields: ClassVar[list[str]] = [
            'id',
            'name_account',
            'balance',
            'currency',
            'type_account',
            'type_account_display',
            'bank',
            'limit_credit',
            'payment_due_date',
            'grace_period_days',
            'user_username',
            'url',
            'delete_url',
            'is_foreign',
        ]
        read_only_fields: ClassVar[list[str]] = ['id']

    def get_url(self, obj: Account) -> str:
        """Get absolute URL for account edit."""
        return obj.get_absolute_url()

    def get_delete_url(self, obj: Account) -> str:
        """Get URL for account deletion."""

        return reverse('finance_account:delete_account', args=[obj.pk])

    def get_is_foreign(self, obj: Account) -> bool:
        """Check if account belongs to another user."""
        request: Any = self.context.get('request')
        if request is None:
            return False

        user: Any = getattr(request, 'user', None)
        if not user or not getattr(user, 'is_authenticated', False):
            return False

        user_id: Any = getattr(user, 'id', None)
        if user_id is None:
            return False

        return obj.user_id != user_id

    def create(self, validated_data: dict[str, Any]) -> Account:
        """Override create to set user from request."""
        request: Any = self.context.get('request')
        if request is None:
            raise serializers.ValidationError(
                _('Не удалось создать счёт без контекста запроса.'),
            )

        user: Any = getattr(request, 'user', None)
        if not user or not getattr(user, 'is_authenticated', False):
            raise serializers.ValidationError(
                _('Не удалось создать счёт без аутентификации пользователя.'),
            )

        validated_data['user'] = user
        return super().create(validated_data)
