"""Serializers for finance account models.

This module provides Django REST Framework serializers for converting
finance account models to and from JSON format for API communication.
"""

from typing import Any, ClassVar

from rest_framework import serializers

from hasta_la_vista_money.finance_account.models import Account


class AccountSerializer(serializers.ModelSerializer[Account]):
    """Serializer for Account model.

    Converts Account model instances to JSON format for API responses,
    including essential account information like name, balance, and currency.
    """

    class Meta:  # type: ignore[misc]
        model = Account
        fields: ClassVar[list[str]] = [
            'id',
            'name_account',
            'balance',
            'currency',
            'type_account',
            'bank',
            'limit_credit',
            'payment_due_date',
            'grace_period_days',
        ]
        read_only_fields: ClassVar[list[str]] = ['id']

    def create(self, validated_data: dict[str, Any]) -> Account:
        """Override create to set user from request."""
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)
