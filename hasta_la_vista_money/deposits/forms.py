from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.bank_constants import (
    BANK_CHOICES,
    BANK_DEFAULT,
)
from hasta_la_vista_money.finance_account.currencies import currency_choices


class CreateDepositForm(forms.Form):
    name = forms.CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
        label=_('Название вклада'),
    )
    bank = forms.ChoiceField(choices=BANK_CHOICES, label=_('Банк'))
    currency = forms.ChoiceField(
        choices=currency_choices(),
        label=_('Валюта'),
    )
    balance = forms.DecimalField(
        min_value=0,
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        label=_('Текущий остаток'),
    )
    opened_on = forms.DateField(
        input_formats=list(constants.HTML5_DATE_INPUT_FORMATS),
        widget=forms.DateInput(attrs={'type': 'date'}),
        label=_('Дата открытия'),
    )
    matures_on = forms.DateField(
        input_formats=list(constants.HTML5_DATE_INPUT_FORMATS),
        widget=forms.DateInput(attrs={'type': 'date'}),
        label=_('Дата окончания'),
    )
    annual_rate = forms.DecimalField(
        min_value=constants.MIN_ANNUAL_RATE,
        max_digits=6,
        decimal_places=2,
        label=_('Фиксированная годовая ставка, %'),
    )

    def clean_bank(self) -> str:
        bank = str(self.cleaned_data['bank'])
        if bank == BANK_DEFAULT:
            raise ValidationError(_('Выберите банк для срочного вклада.'))
        return bank

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean() or {}
        opened_on = cleaned_data.get('opened_on')
        matures_on = cleaned_data.get('matures_on')
        if opened_on and matures_on and matures_on < opened_on:
            raise ValidationError(
                _('Дата окончания вклада не может быть раньше даты открытия.'),
            )
        return cleaned_data
