"""Common serializers for API validation."""

from typing import Any

from rest_framework import serializers


class GroupQuerySerializer(serializers.Serializer[Any]):
    """Serializer для валидации query параметра group_id."""

    group_id = serializers.CharField(required=False, default='my', allow_blank=True)


class BudgetTypeSerializer(serializers.Serializer[Any]):
    """Serializer для валидации типа бюджета."""

    type = serializers.ChoiceField(
        choices=['expense', 'income'],
        required=True,
    )
