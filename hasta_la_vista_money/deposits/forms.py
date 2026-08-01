from typing import TYPE_CHECKING, Any, cast

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.deposits.models import DepositPrincipalEvent
from hasta_la_vista_money.finance_account.bank_constants import (
    BANK_CHOICES,
    BANK_DEFAULT,
)
from hasta_la_vista_money.finance_account.currencies import currency_choices
from hasta_la_vista_money.finance_account.models import Account

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User


def _deposit_date_widget() -> forms.DateInput:
    return forms.DateInput(
        format=constants.HTML5_DATE_INPUT_FORMAT,
        attrs={
            'type': 'date',
            'lang': 'ru-RU',
            'data-flatpickr': 'true',
            'data-flatpickr-mode': 'date',
            'placeholder': 'ДД.ММ.ГГГГ',
        },
    )


class CreateDepositForm(forms.Form):
    opening_method = forms.ChoiceField(
        choices=DepositPrincipalEvent.Type.choices,
        label=_('Как начать учёт'),
        widget=forms.RadioSelect,
    )
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
        label=_('Тело вклада'),
    )
    source_account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        required=False,
        label=_('Счёт для финансирования'),
        help_text=_('Только собственный счёт в валюте вклада.'),
    )
    tracking_started_on = forms.DateField(
        required=False,
        input_formats=list(constants.HTML5_DATE_INPUT_FORMATS),
        widget=_deposit_date_widget(),
        label=_('Дата начала учёта'),
    )
    opened_on = forms.DateField(
        input_formats=list(constants.HTML5_DATE_INPUT_FORMATS),
        widget=_deposit_date_widget(),
        label=_('Дата открытия'),
    )
    matures_on = forms.DateField(
        input_formats=list(constants.HTML5_DATE_INPUT_FORMATS),
        widget=_deposit_date_widget(),
        label=_('Дата окончания'),
    )
    annual_rate = forms.DecimalField(
        min_value=constants.MIN_ANNUAL_RATE,
        max_digits=6,
        decimal_places=2,
        label=_('Фиксированная годовая ставка, %'),
    )

    def __init__(
        self,
        *args: Any,
        user: 'User | None' = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        if user is not None:
            source_account_field = cast(
                'forms.ModelChoiceField[Account]',
                self.fields['source_account'],
            )
            source_account_field.queryset = Account.objects.filter(
                user=user,
            ).exclude(type_account=constants.ACCOUNT_TYPE_DEPOSIT)

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
        opening_method = cleaned_data.get('opening_method')
        if (
            opening_method == DepositPrincipalEvent.Type.FUNDING
            and cleaned_data.get('source_account') is None
        ):
            self.add_error(
                'source_account',
                _('Выберите счёт для финансирования вклада.'),
            )
        if (
            opening_method == DepositPrincipalEvent.Type.OPENING_POSITION
            and cleaned_data.get('tracking_started_on') is None
        ):
            self.add_error(
                'tracking_started_on',
                _('Укажите дату начала учёта вклада.'),
            )
        return cleaned_data
