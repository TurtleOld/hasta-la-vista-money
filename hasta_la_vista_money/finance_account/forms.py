from typing import Any, Dict

from django.forms import (
    CharField,
    ChoiceField,
    DateTimeInput,
    DecimalField,
    ModelChoiceField,
    ModelForm,
    Textarea,
)
from django.utils.translation import gettext_lazy as _
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)


class AddAccountForm(ModelForm[Account]):
    name_account = CharField(
        label=_('Наименование счёта'),
        help_text=_('Введите наименование счёта. Максимальная длина 250 символов.'),
    )
    type_account = ChoiceField(
        choices=Account.TYPE_ACCOUNT_LIST,
        label=_('Тип счёта'),
        help_text=_('Выберите из списка тип счёта'),
    )
    balance = DecimalField(
        label=_('Баланс'),
        help_text=_(
            'Введите начальный баланс, который есть сейчас на счёту в банке\\в наличной валюте.\nМаксимальная длина 20 символов.'
        ),
    )
    currency = ChoiceField(
        choices=Account.CURRENCY_LIST,
        label=_('Валюта счёта'),
        help_text=_('Выберите из списка валюту счёта'),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['type_account'].initial = Account.TYPE_ACCOUNT_LIST[1][0]

    class Meta:
        model = Account
        fields = ['name_account', 'type_account', 'balance', 'currency']


class TransferMoneyAccountForm(ModelForm[Account]):
    def __init__(self, user, *args, **kwargs):
        """
        Конструктов класса инициализирующий две поля формы.

        :param user:
        :param args:
        :param kwargs:
        """
        super().__init__(*args, **kwargs)
        self.fields['from_account'] = ModelChoiceField(
            label=_('Со счёта:'),
            queryset=Account.objects.filter(user=user),
        )
        self.fields['to_account'] = ModelChoiceField(
            label=_('На счёт:'),
            queryset=Account.objects.filter(user=user),
        )
        self.fields['amount'] = DecimalField(
            label=_('Сумма перевода:'),
            max_digits=constants.TWENTY,
            decimal_places=constants.TWO,
        )
        self.fields['notes'] = CharField(
            label=_('Заметка'),
            required=False,
            help_text=constants.ACCOUNT_FORM_NOTES,
            widget=Textarea(
                attrs={
                    'rows': 3,
                    'maxlength': constants.TWO_HUNDRED_FIFTY,
                },
            ),
        )

    def clean(self) -> Dict[str, Any]:
        cleaned_data = super().clean()
        from_account = cleaned_data.get('from_account')
        to_account = cleaned_data.get('to_account')
        amount = cleaned_data.get('amount')

        if from_account and to_account and from_account == to_account:
            self.add_error(
                'to_account',
                constants.ANOTHER_ACCRUAL_ACCOUNT,
            )

        if from_account and amount and amount > from_account.balance:
            self.add_error(
                'from_account',
                constants.SUCCESS_MESSAGE_INSUFFICIENT_FUNDS,
            )

        return cleaned_data

    def save(self, commit=True):
        from_account = self.cleaned_data['from_account']
        to_account = self.cleaned_data['to_account']
        amount = self.cleaned_data['amount']
        exchange_date = self.cleaned_data['exchange_date']
        notes = self.cleaned_data['notes']

        if from_account.transfer_money(to_account, amount):
            return TransferMoneyLog.objects.create(
                user=from_account.user,
                from_account=from_account,
                to_account=to_account,
                amount=amount,
                exchange_date=exchange_date,
                notes=notes,
            )

        return None

    class Meta:
        model = TransferMoneyLog
        fields = [
            'from_account',
            'to_account',
            'exchange_date',
            'amount',
            'notes',
        ]
        labels = {'exchange_date': _('Дата перевода')}
        widgets = {
            'exchange_date': DateTimeInput(
                attrs={'type': 'datetime-local', 'class': 'form-control'},
            ),
        }
