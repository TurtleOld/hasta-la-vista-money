from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from django import forms
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy

from hasta_la_vista_money import constants
from hasta_la_vista_money.deposits.models import (
    DepositCapitalizationEvent,
    DepositInterestForecast,
    DepositPrincipalEvent,
    DepositTerm,
)
from hasta_la_vista_money.finance_account.bank_constants import (
    BANK_DEFAULT,
)
from hasta_la_vista_money.finance_account.currencies import currency_choices
from hasta_la_vista_money.finance_account.models import Account, Bank

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


class ReverseDepositEventForm(forms.Form):
    reason = forms.CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
        label=_('Причина аннулирования'),
        widget=forms.Textarea(attrs={'rows': 2}),
    )
    reversed_on = forms.DateField(
        input_formats=list(constants.HTML5_DATE_INPUT_FORMATS),
        widget=_deposit_date_widget(),
        label=_('Дата аннулирования'),
    )

    def clean_reason(self) -> str:
        reason = cast('str', self.cleaned_data['reason']).strip()
        if not reason:
            raise ValidationError(_('Укажите причину аннулирования.'))
        return reason


class CreateDepositForm(forms.Form):
    early_closure_annual_rate = forms.DecimalField(
        required=False,
        min_value=0,
        max_digits=6,
        decimal_places=2,
        label=_('Ставка досрочного расторжения, %'),
    )
    early_closure_recalculation_scope = forms.ChoiceField(
        choices=DepositTerm.EarlyClosureRecalculationScope.choices,
        initial=DepositTerm.EarlyClosureRecalculationScope.UNSUPPORTED,
        required=False,
        label=_('Область пересчёта при досрочном расторжении'),
    )
    early_closure_withdrawn_amount = forms.DecimalField(
        required=False,
        min_value=0,
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        label=_('Сумма для пересчёта'),
    )
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
    interest_payout_destination = forms.ChoiceField(
        choices=DepositTerm.PayoutDestination.choices,
        initial=DepositTerm.PayoutDestination.CAPITALIZATION,
        required=False,
        label=_('Обычный способ выплаты процентов'),
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
    bank = forms.ModelChoiceField(
        queryset=Bank.objects.none(),
        label=_('Банк'),
    )
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
        bank_field = cast(
            'forms.ModelChoiceField[Bank]',
            self.fields['bank'],
        )
        if user is not None:
            source_account_field = cast(
                'forms.ModelChoiceField[Account]',
                self.fields['source_account'],
            )
            source_account_field.queryset = (
                Account.objects.available_for_operations()
                .filter(user=user)
                .exclude(type_account=constants.ACCOUNT_TYPE_DEPOSIT)
            )
            bank_field.queryset = Bank.objects.filter(
                models.Q(is_system=True) | models.Q(user=user),
            )
        else:
            bank_field.queryset = Bank.objects.filter(
                is_system=True,
            )

    def clean_bank(self) -> str:
        bank = cast('Bank | None', self.cleaned_data.get('bank'))
        if bank is None or bank.code == BANK_DEFAULT:
            raise ValidationError(_('Выберите банк для срочного вклада.'))
        return bank.code

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
        cleaned_data.setdefault('interest_payout_destination', None)
        if not cleaned_data['interest_payout_destination']:
            cleaned_data['interest_payout_destination'] = (
                DepositTerm.PayoutDestination.CAPITALIZATION
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
        self._clean_early_closure_terms(cleaned_data)
        return cleaned_data

    def _clean_early_closure_terms(
        self,
        cleaned_data: dict[str, Any],
    ) -> None:
        scope = cleaned_data.get('early_closure_recalculation_scope') or (
            DepositTerm.EarlyClosureRecalculationScope.UNSUPPORTED
        )
        cleaned_data['early_closure_recalculation_scope'] = scope
        rate = cleaned_data.get('early_closure_annual_rate')
        if (
            scope != DepositTerm.EarlyClosureRecalculationScope.UNSUPPORTED
            and rate is None
        ):
            self.add_error(
                'early_closure_annual_rate',
                _('Укажите ставку досрочного расторжения.'),
            )
        if (
            scope == DepositTerm.EarlyClosureRecalculationScope.WITHDRAWN_AMOUNT
            and cleaned_data.get('early_closure_withdrawn_amount') is None
        ):
            self.add_error(
                'early_closure_withdrawn_amount',
                _('Укажите сумму для пересчёта.'),
            )

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


class RenewDepositForm(CreateDepositForm):
    """Collect explicit contract terms for a deposit's next term."""

    def __init__(
        self,
        *args: Any,
        term: DepositTerm,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        for field_name in (
            'opening_method',
            'name',
            'bank',
            'currency',
            'balance',
            'source_account',
            'tracking_started_on',
        ):
            self.fields.pop(field_name)

        next_opened_on = term.matures_on + timedelta(days=1)
        duration = term.matures_on - term.opened_on
        renewal_delta = next_opened_on - term.opened_on
        latest_rate = term.rate_periods.order_by('-starts_on').first()
        custom_dates = ', '.join(
            (scheduled.payout_on + renewal_delta).strftime('%d/%m/%Y')
            for scheduled in term.payout_schedule_dates.all()
        )
        self.initial.update(
            {
                'opened_on': next_opened_on,
                'matures_on': next_opened_on + duration,
                'annual_rate': (
                    latest_rate.annual_rate if latest_rate is not None else None
                ),
                'rate_kind': term.rate_kind,
                'day_count_convention': term.day_count_convention,
                'accrual_start_included': term.accrual_start_included,
                'accrual_end_included': term.accrual_end_included,
                'payout_schedule_kind': term.payout_schedule_kind,
                'custom_payout_dates': custom_dates,
                'business_day_convention': term.business_day_convention,
                'interest_payout_destination': (
                    term.interest_payout_destination
                ),
                'withdrawal_allowed': term.withdrawal_allowed,
                'minimum_withdrawal_amount': term.minimum_withdrawal_amount,
                'maximum_withdrawal_amount': term.maximum_withdrawal_amount,
                'withdrawal_deadline': (
                    term.withdrawal_deadline + renewal_delta
                    if term.withdrawal_deadline is not None
                    else None
                ),
                'minimum_balance': term.minimum_balance,
                'top_up_allowed': term.top_up_allowed,
                'minimum_top_up_amount': term.minimum_top_up_amount,
                'maximum_top_up_amount': term.maximum_top_up_amount,
                'top_up_deadline': (
                    term.top_up_deadline + renewal_delta
                    if term.top_up_deadline is not None
                    else None
                ),
                'maximum_balance': term.maximum_balance,
            },
        )


class TopUpDepositForm(forms.Form):
    source_account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        label=pgettext_lazy('deposits', 'Счёт списания'),
    )
    amount = forms.DecimalField(
        min_value=constants.MIN_MONEY_AMOUNT,
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        label=pgettext_lazy('deposits', 'Сумма пополнения'),
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
        field.queryset = (
            Account.objects.available_for_operations()
            .filter(user=user, currency=currency)
            .exclude(type_account=constants.ACCOUNT_TYPE_DEPOSIT)
        )

    def clean_exception_reason(self) -> str:
        return str(self.cleaned_data['exception_reason']).strip()


class CapitalizeInterestForm(forms.Form):
    forecast = forms.ModelChoiceField(
        queryset=DepositInterestForecast.objects.none(),
        required=False,
        label=_('Ожидаемая выплата'),
    )
    destination = forms.ChoiceField(
        choices=DepositCapitalizationEvent.Destination.choices,
        required=False,
        label=_('Фактическое назначение выплаты'),
    )
    destination_account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        required=False,
        label=_('Собственный счёт для выплаты'),
    )
    gross = forms.DecimalField(
        min_value=Decimal(0),
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        label=_('Сумма начисленных процентов (в валюте вклада)'),
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
        label=_('Причина внеплановой выплаты'),
    )

    def __init__(
        self,
        *args: Any,
        term: DepositTerm,
        user: 'User | None' = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.initial.setdefault(
            'destination',
            term.interest_payout_destination,
        )
        field = cast(
            'forms.ModelChoiceField[DepositInterestForecast]',
            self.fields['forecast'],
        )
        field.queryset = term.interest_forecasts.filter(confirmed=False)
        account_field = cast(
            'forms.ModelChoiceField[Account]',
            self.fields['destination_account'],
        )
        if user is not None:
            account_field.queryset = (
                Account.objects.available_for_operations()
                .filter(
                    user=user,
                    currency=term.deposit.account.currency,
                )
                .exclude(pk=term.deposit.account_id)
            )

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        if cleaned is None:
            return cleaned
        gross = cleaned.get('gross')
        withholding = cleaned.get('withholding')
        net = cleaned.get('net')
        forecast = cleaned.get('forecast')
        reason = str(cleaned.get('reason', '')).strip()
        destination = (
            cleaned.get('destination') or (self.initial['destination'])
        )
        destination_account = cleaned.get('destination_account')
        cleaned['destination'] = destination
        if gross is None or withholding is None or net is None:
            return cleaned
        if not forecast and not reason:
            raise ValidationError(
                _(
                    'Выберите ожидаемую выплату или укажите причину '
                    'внеплановой выплаты.',
                ),
            )
        if (
            destination
            == DepositCapitalizationEvent.Destination.INTERNAL_ACCOUNT
            and destination_account is None
        ):
            self.add_error(
                'destination_account',
                _('Выберите собственный счёт для выплаты процентов.'),
            )
        if (
            destination
            != DepositCapitalizationEvent.Destination.INTERNAL_ACCOUNT
            and destination_account is not None
        ):
            self.add_error(
                'destination_account',
                _('Счёт можно указать только для внутренней выплаты.'),
            )
        return cleaned


class CloseMaturedDepositForm(forms.Form):
    destination = forms.ChoiceField(
        choices=(
            (
                DepositCapitalizationEvent.Destination.INTERNAL_ACCOUNT,
                _('На собственный счёт'),
            ),
            (
                DepositCapitalizationEvent.Destination.EXTERNAL,
                _('Внешнему получателю'),
            ),
        ),
        label=_('Назначение возврата'),
    )
    destination_account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        required=False,
        label=_('Собственный счёт для возврата'),
    )
    forecast = forms.ModelChoiceField(
        queryset=DepositInterestForecast.objects.none(),
        required=False,
        label=_('Ожидаемая финальная выплата'),
    )
    principal = forms.DecimalField(
        min_value=Decimal(),
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        label=_('Возвращаемое тело вклада'),
    )
    gross = forms.DecimalField(
        min_value=Decimal(),
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        label=_('Финальные проценты gross'),
    )
    withholding = forms.DecimalField(
        min_value=Decimal(),
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        initial=Decimal(),
        label=_('Удержание'),
    )
    net = forms.DecimalField(
        min_value=Decimal(),
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        label=_('Финальные проценты net'),
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

    def __init__(
        self,
        *args: Any,
        term: DepositTerm,
        user: 'User',
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.term = term
        account_field = cast(
            'forms.ModelChoiceField[Account]',
            self.fields['destination_account'],
        )
        account_field.queryset = (
            Account.objects.available_for_operations()
            .filter(user=user, currency=term.deposit.account.currency)
            .exclude(type_account=constants.ACCOUNT_TYPE_DEPOSIT)
        )
        forecast_field = cast(
            'forms.ModelChoiceField[DepositInterestForecast]',
            self.fields['forecast'],
        )
        forecast_field.queryset = term.interest_forecasts.filter(
            confirmed=False,
            period_ends_on=term.matures_on,
        )
        self.initial.setdefault(
            'principal',
            term.deposit.account.balance,
        )
        self.initial.setdefault('posting_on', timezone.localdate())
        self.initial.setdefault('value_on', timezone.localdate())

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        if cleaned is None:
            return cleaned
        destination = cleaned.get('destination')
        account = cleaned.get('destination_account')
        principal = cleaned.get('principal')
        gross = cleaned.get('gross')
        withholding = cleaned.get('withholding')
        net = cleaned.get('net')
        posting_on = cleaned.get('posting_on')
        value_on = cleaned.get('value_on')
        if (
            destination
            == DepositCapitalizationEvent.Destination.INTERNAL_ACCOUNT
            and account is None
        ):
            self.add_error(
                'destination_account',
                _('Выберите собственный счёт для возврата вклада.'),
            )
        if (
            destination
            != (DepositCapitalizationEvent.Destination.INTERNAL_ACCOUNT)
            and account is not None
        ):
            self.add_error(
                'destination_account',
                _('Для внешнего возврата счёт не указывается.'),
            )
        if (
            principal is not None
            and principal != self.term.deposit.account.balance
        ):
            self.add_error(
                'principal',
                _('Возвращаемое тело должно совпадать с остатком вклада.'),
            )
        if (
            isinstance(gross, Decimal)
            and isinstance(withholding, Decimal)
            and isinstance(net, Decimal)
            and gross - withholding != net
        ):
            self.add_error(
                'net',
                _('Чистые проценты должны равняться gross минус удержание.'),
            )
        for field_name, actual_on in (
            ('posting_on', posting_on),
            ('value_on', value_on),
        ):
            if actual_on is not None and actual_on < self.term.matures_on:
                self.add_error(
                    field_name,
                    _('Дата закрытия не может быть раньше окончания срока.'),
                )
        return cleaned


class ForecastEarlyClosureForm(forms.Form):
    closure_on = forms.DateField(
        input_formats=list(constants.HTML5_DATE_INPUT_FORMATS),
        widget=_deposit_date_widget(),
        label=_('Дата досрочного закрытия'),
    )

    def __init__(
        self,
        *args: Any,
        term: DepositTerm,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.term = term
        self.initial.setdefault('closure_on', timezone.localdate())

    def clean_closure_on(self) -> date:
        closure_on = cast('date', self.cleaned_data['closure_on'])
        if not self.term.opened_on <= closure_on < self.term.matures_on:
            raise ValidationError(
                _('Дата досрочного закрытия должна попадать в срок вклада.'),
            )
        return closure_on


class CloseDepositEarlyForm(CloseMaturedDepositForm):
    prior_interest_adjustment = forms.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
        initial=Decimal(),
        label=_('Корректировка ранее выплаченных процентов'),
        help_text=_('Возврат банку указывается отрицательной суммой.'),
    )
    closure_reason = forms.CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
        widget=forms.Textarea(attrs={'rows': 2}),
        label=_('Причина досрочного закрытия'),
    )

    def __init__(
        self,
        *args: Any,
        term: DepositTerm,
        user: 'User',
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, term=term, user=user, **kwargs)
        self.fields.pop('forecast')

    def clean(self) -> dict[str, Any] | None:
        cleaned = forms.Form.clean(self)
        if cleaned is None:
            return cleaned
        destination = cleaned.get('destination')
        account = cleaned.get('destination_account')
        principal = cleaned.get('principal')
        gross = cleaned.get('gross')
        withholding = cleaned.get('withholding')
        net = cleaned.get('net')
        posting_on = cleaned.get('posting_on')
        value_on = cleaned.get('value_on')
        if (
            destination
            == DepositCapitalizationEvent.Destination.INTERNAL_ACCOUNT
            and account is None
        ):
            self.add_error(
                'destination_account',
                _('Выберите собственный счёт для возврата вклада.'),
            )
        if (
            destination
            != DepositCapitalizationEvent.Destination.INTERNAL_ACCOUNT
            and account is not None
        ):
            self.add_error(
                'destination_account',
                _('Для внешнего возврата счёт не указывается.'),
            )
        if (
            principal is not None
            and principal != self.term.deposit.account.balance
        ):
            self.add_error(
                'principal',
                _('Возвращаемое тело должно совпадать с остатком вклада.'),
            )
        if (
            isinstance(gross, Decimal)
            and isinstance(withholding, Decimal)
            and isinstance(net, Decimal)
            and gross - withholding != net
        ):
            self.add_error(
                'net',
                _('Чистые проценты должны равняться gross минус удержание.'),
            )
        for field_name, actual_on in (
            ('posting_on', posting_on),
            ('value_on', value_on),
        ):
            if actual_on is not None and not (
                self.term.opened_on <= actual_on < self.term.matures_on
            ):
                self.add_error(
                    field_name,
                    _(
                        'Дата досрочного закрытия должна попадать '
                        'в срок вклада.',
                    ),
                )
        return cleaned


class CorrectPayoutScheduleForm(forms.Form):
    """Correct an already-existing term's payout schedule in place.

    Offers the same full set of choices as at deposit creation (see
    CreateDepositForm), without narrowing — including CUSTOM/EXTERNAL —
    so the correction can describe any real bank condition (ADR-0008).
    """

    payout_schedule_kind = forms.ChoiceField(
        choices=DepositTerm.PayoutScheduleKind.choices,
        label=_('Расписание выплат'),
    )
    interest_payout_destination = forms.ChoiceField(
        choices=DepositTerm.PayoutDestination.choices,
        label=_('Обычный способ выплаты процентов'),
    )

    def __init__(
        self,
        *args: Any,
        term: DepositTerm,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.initial.setdefault(
            'payout_schedule_kind',
            term.payout_schedule_kind,
        )
        self.initial.setdefault(
            'interest_payout_destination',
            term.interest_payout_destination,
        )


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
        field.queryset = (
            Account.objects.available_for_operations()
            .filter(user=user, currency=currency)
            .exclude(type_account=constants.ACCOUNT_TYPE_DEPOSIT)
        )

    def clean_exception_reason(self) -> str:
        return str(self.cleaned_data['exception_reason']).strip()
