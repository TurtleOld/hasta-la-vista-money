from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.deposits.models import (
    DepositInterestForecast,
    DepositPrincipalEvent,
    DepositTerm,
)
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


def _parse_html5_date(token: str) -> date:
    for date_format in constants.HTML5_DATE_INPUT_FORMATS:
        try:
            return (
                datetime.strptime(token, date_format)
                .replace(
                    tzinfo=UTC,
                )
                .date()
            )
        except ValueError:
            continue
    message = _('Неверный формат даты: %(token)s') % {'token': token}
    raise ValidationError(message)


class CreateDepositForm(forms.Form):
    withdrawal_allowed = forms.BooleanField(
        required=False,
        label=_('Разрешено частичное снятие'),
    )
    minimum_withdrawal_amount = forms.DecimalField(
        required=False,
        min_value=constants.MIN_MONEY_AMOUNT,
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        label=_('Минимальная сумма снятия'),
    )
    maximum_withdrawal_amount = forms.DecimalField(
        required=False,
        min_value=constants.MIN_MONEY_AMOUNT,
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        label=_('Максимальная сумма снятия'),
    )
    withdrawal_deadline = forms.DateField(
        required=False,
        input_formats=list(constants.HTML5_DATE_INPUT_FORMATS),
        widget=_deposit_date_widget(),
        label=_('Крайний срок снятия'),
    )
    minimum_balance = forms.DecimalField(
        required=False,
        min_value=0,
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        initial=Decimal(),
        label=_('Неснижаемый остаток'),
    )
    top_up_allowed = forms.BooleanField(
        required=False,
        label=_('Разрешено пополнение'),
    )
    minimum_top_up_amount = forms.DecimalField(
        required=False,
        min_value=constants.MIN_MONEY_AMOUNT,
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        label=_('Минимальная сумма пополнения'),
    )
    maximum_top_up_amount = forms.DecimalField(
        required=False,
        min_value=constants.MIN_MONEY_AMOUNT,
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        label=_('Максимальная сумма пополнения'),
    )
    top_up_deadline = forms.DateField(
        required=False,
        input_formats=list(constants.HTML5_DATE_INPUT_FORMATS),
        widget=_deposit_date_widget(),
        label=_('Крайний срок пополнения'),
    )
    maximum_balance = forms.DecimalField(
        required=False,
        min_value=constants.MIN_MONEY_AMOUNT,
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        label=_('Максимальный остаток после пополнения'),
    )
    opening_method = forms.ChoiceField(
        choices=DepositPrincipalEvent.Type.choices,
        label=_('Как начать учёт'),
        widget=forms.RadioSelect,
    )
    rate_kind = forms.ChoiceField(
        choices=DepositTerm.RateKind.choices,
        label=_('Тип ставки'),
        widget=forms.RadioSelect,
    )
    day_count_convention = forms.ChoiceField(
        choices=DepositTerm.DayCountConvention.choices,
        initial=DepositTerm.DayCountConvention.ACTUAL_ACTUAL,
        required=False,
        label=_('Метод расчёта дней'),
    )
    accrual_start_included = forms.BooleanField(
        required=False,
        initial=True,
        label=_('Учитывать день поступления средств'),
    )
    accrual_end_included = forms.BooleanField(
        required=False,
        initial=False,
        label=_('Учитывать день возврата вклада'),
    )
    payout_schedule_kind = forms.ChoiceField(
        choices=DepositTerm.PayoutScheduleKind.choices,
        initial=DepositTerm.PayoutScheduleKind.MATURITY,
        required=False,
        label=_('Расписание выплат'),
    )
    custom_payout_dates = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 2}),
        label=_('Даты индивидуального расписания'),
        help_text=_(
            'Только для индивидуального расписания. Через запятую или '
            'с новой строки, формат ДД/ММ/ГГГГ. Дата окончания срока '
            'учитывается автоматически.',
        ),
    )
    business_day_convention = forms.ChoiceField(
        choices=DepositTerm.BusinessDayConvention.choices,
        initial=DepositTerm.BusinessDayConvention.NONE,
        required=False,
        label=_('Перенос выплаты на рабочий день'),
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

    def clean_custom_payout_dates(self) -> list[date]:
        raw = str(self.cleaned_data.get('custom_payout_dates', '')).strip()
        if not raw:
            return []
        tokens = [
            token.strip()
            for token in raw.replace('\n', ',').split(',')
            if token.strip()
        ]
        parsed_dates = [_parse_html5_date(token) for token in tokens]
        return sorted(parsed_dates)

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean() or {}
        cleaned_data.setdefault('day_count_convention', None)
        if not cleaned_data['day_count_convention']:
            cleaned_data['day_count_convention'] = (
                DepositTerm.DayCountConvention.ACTUAL_ACTUAL
            )
        cleaned_data.setdefault('payout_schedule_kind', None)
        if not cleaned_data['payout_schedule_kind']:
            cleaned_data['payout_schedule_kind'] = (
                DepositTerm.PayoutScheduleKind.MATURITY
            )
        cleaned_data.setdefault('business_day_convention', None)
        if not cleaned_data['business_day_convention']:
            cleaned_data['business_day_convention'] = (
                DepositTerm.BusinessDayConvention.NONE
            )
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
        if cleaned_data.get(
            'payout_schedule_kind',
        ) == DepositTerm.PayoutScheduleKind.CUSTOM and not cleaned_data.get(
            'custom_payout_dates',
        ):
            self.add_error(
                'custom_payout_dates',
                _(
                    'Для индивидуального расписания укажите хотя бы одну '
                    'дату выплаты.',
                ),
            )
        self._clean_withdrawal_terms(cleaned_data)
        self._clean_top_up_terms(cleaned_data)
        return cleaned_data

    def _clean_withdrawal_terms(
        self,
        cleaned_data: dict[str, Any],
    ) -> None:
        if not cleaned_data.get('withdrawal_allowed'):
            for field_name in (
                'minimum_withdrawal_amount',
                'maximum_withdrawal_amount',
                'withdrawal_deadline',
            ):
                cleaned_data[field_name] = None
            cleaned_data['minimum_balance'] = Decimal()
            return
        minimum = cleaned_data.get('minimum_withdrawal_amount')
        maximum = cleaned_data.get('maximum_withdrawal_amount')
        if minimum and maximum and minimum > maximum:
            self.add_error(
                'maximum_withdrawal_amount',
                _('Максимальная сумма не может быть меньше минимальной.'),
            )

    def _clean_top_up_terms(self, cleaned_data: dict[str, Any]) -> None:
        if not cleaned_data.get('top_up_allowed'):
            for field_name in (
                'minimum_top_up_amount',
                'maximum_top_up_amount',
                'top_up_deadline',
                'maximum_balance',
            ):
                cleaned_data[field_name] = None
            return
        minimum = cleaned_data.get('minimum_top_up_amount')
        maximum = cleaned_data.get('maximum_top_up_amount')
        if minimum and maximum and minimum > maximum:
            self.add_error(
                'maximum_top_up_amount',
                _('Максимальная сумма не может быть меньше минимальной.'),
            )


class TopUpDepositForm(forms.Form):
    source_account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        label=_('Счёт списания'),
    )
    amount = forms.DecimalField(
        min_value=constants.MIN_MONEY_AMOUNT,
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        label=_('Сумма пополнения'),
    )
    effective_on = forms.DateField(
        input_formats=list(constants.HTML5_DATE_INPUT_FORMATS),
        widget=_deposit_date_widget(),
        label=_('Дата валютирования'),
    )
    exception_reason = forms.CharField(
        required=False,
        max_length=constants.TWO_HUNDRED_FIFTY,
        widget=forms.Textarea(attrs={'rows': 2}),
        label=_('Причина фактического исключения'),
    )

    def __init__(
        self,
        *args: Any,
        user: 'User',
        currency: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        field = cast(
            'forms.ModelChoiceField[Account]',
            self.fields['source_account'],
        )
        field.queryset = Account.objects.filter(
            user=user,
            currency=currency,
        ).exclude(type_account=constants.ACCOUNT_TYPE_DEPOSIT)

    def clean_exception_reason(self) -> str:
        return str(self.cleaned_data['exception_reason']).strip()


class CapitalizeInterestForm(forms.Form):
    forecast = forms.ModelChoiceField(
        queryset=DepositInterestForecast.objects.none(),
        required=False,
        label=_('Ожидаемая выплата'),
    )
    gross = forms.DecimalField(
        min_value=Decimal(0),
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        label=_('Валовый процентный доход'),
    )
    withholding = forms.DecimalField(
        min_value=Decimal(0),
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        initial=Decimal(0),
        label=_('Удержание (налог)'),
    )
    net = forms.DecimalField(
        min_value=Decimal('0.01'),
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        label=_('Чистое зачисление'),
    )
    posting_on = forms.DateField(
        input_formats=list(constants.HTML5_DATE_INPUT_FORMATS),
        widget=_deposit_date_widget(),
        label=_('Дата проводки'),
    )
    value_on = forms.DateField(
        input_formats=list(constants.HTML5_DATE_INPUT_FORMATS),
        widget=_deposit_date_widget(),
        label=_('Дата валютирования'),
    )
    reason = forms.CharField(
        required=False,
        max_length=constants.TWO_HUNDRED_FIFTY,
        widget=forms.Textarea(attrs={'rows': 2}),
        label=_('Причина внеплановой капитализации'),
    )

    def __init__(
        self,
        *args: Any,
        term: DepositTerm,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        field = cast(
            'forms.ModelChoiceField[DepositInterestForecast]',
            self.fields['forecast'],
        )
        field.queryset = term.interest_forecasts.filter(confirmed=False)

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        if cleaned is None:
            return cleaned
        gross = cleaned.get('gross')
        withholding = cleaned.get('withholding')
        net = cleaned.get('net')
        forecast = cleaned.get('forecast')
        reason = str(cleaned.get('reason', '')).strip()
        if gross is None or withholding is None or net is None:
            return cleaned
        if not forecast and not reason:
            raise ValidationError(
                _(
                    'Выберите ожидаемую выплату или укажите причину '
                    'внеплановой капитализации.',
                ),
            )
        return cleaned


class AddFloatingRatePeriodForm(forms.Form):
    starts_on = forms.DateField(
        input_formats=list(constants.HTML5_DATE_INPUT_FORMATS),
        widget=_deposit_date_widget(),
        label=_('Дата начала действия ставки'),
    )
    annual_rate = forms.DecimalField(
        min_value=constants.MIN_ANNUAL_RATE,
        max_digits=6,
        decimal_places=2,
        label=_('Новая годовая ставка, %'),
    )
    note = forms.CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
        label=_('Пояснение к изменению ставки'),
        help_text=_(
            'Например: «по договору с банком» или «КС ЦБ РФ + 2%». '
            'Без привязки к конкретному внешнему источнику.',
        ),
    )

    def clean_note(self) -> str:
        note = str(self.cleaned_data['note']).strip()
        if not note:
            raise ValidationError(
                _('Укажите пояснение к изменению ставки.'),
            )
        return note


class WithdrawDepositForm(forms.Form):
    destination_account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        label=_('Счёт зачисления'),
    )
    amount = forms.DecimalField(
        min_value=Decimal('0.01'),
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        label=_('Сумма снятия'),
    )
    effective_on = forms.DateField(
        input_formats=list(constants.HTML5_DATE_INPUT_FORMATS),
        widget=_deposit_date_widget(),
        label=_('Дата валютирования'),
    )
    exception_reason = forms.CharField(
        required=False,
        max_length=constants.TWO_HUNDRED_FIFTY,
        widget=forms.Textarea(attrs={'rows': 2}),
        label=_('Причина фактического исключения'),
    )

    def __init__(
        self,
        *args: Any,
        user: 'User',
        currency: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        field = cast(
            'forms.ModelChoiceField[Account]',
            self.fields['destination_account'],
        )
        field.queryset = Account.objects.filter(
            user=user,
            currency=currency,
        ).exclude(type_account=constants.ACCOUNT_TYPE_DEPOSIT)

    def clean_exception_reason(self) -> str:
        return str(self.cleaned_data['exception_reason']).strip()
