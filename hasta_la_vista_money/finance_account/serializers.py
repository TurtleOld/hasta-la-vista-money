"""Serializers for finance account models.

This module provides Django REST Framework serializers for converting
finance account models to and from JSON format for API communication.
"""

from rest_framework import serializers
from typing import ClassVar

from hasta_la_vista_money.finance_account.models import Account


class AccountSerializer(serializers.ModelSerializer):
    """Serializer for Account model.

    Converts Account model instances to JSON format for API responses,
    including essential account information like name, balance, and currency.
    """

    class Meta:
        model = Account
        fields: ClassVar[list[str]] = ['id', 'name_account', 'balance', 'currency']
