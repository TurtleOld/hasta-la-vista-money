"""DRF serializers for budget API input."""

from typing import Any

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from hasta_la_vista_money.finance_account.currencies import currency_choices


class BudgetCurrencySerializer(serializers.Serializer[dict[str, str]]):
    """Optional currency of a saved limit or plan."""

    currency = serializers.ChoiceField(
        choices=[],
        required=False,
        allow_blank=True,
        error_messages={'invalid_choice': _('Неизвестная валюта.')},
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        field = self.fields['currency']
        field.choices = currency_choices()  # type: ignore[attr-defined]
