"""Модуль форм по кредитам."""

from django.forms import (
    ChoiceField,
    DateTimeField,
    DateTimeInput,
    DecimalField,
    IntegerField,
    ModelChoiceField,
)
from django.utils.translation import gettext_lazy as _
from hasta_la_vista_money.commonlogic.forms import BaseForm
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.loan.models import Loan, PaymentMakeLoan


class LoanForm(BaseForm):
    date = DateTimeField(
        label=_('Дата'),
        widget=DateTimeInput(
            attrs={
                'type': 'datetime-local',
                'class': 'form-control',
            },
        ),
        help_text=_('Укажите дату начала кредита'),
    )

    type_loan = ChoiceField(
        choices=Loan.TYPE_LOAN,
        label=_('Тип кредита'),
        help_text=_('Выберите тип кредита из доступных вариантов. '),
    )

    loan_amount = DecimalField(
        label=_('Сумма кредита'),
        help_text=_('Введите сумму кредита в рублях'),
    )

    annual_interest_rate = DecimalField(
        label=_('Годовая ставка в %'),
        help_text=_('Введите годовую процентную ставку по кредиту'),
    )

    period_loan = IntegerField(
        label=_('Срок кредита в месяцах'),
        help_text=_('Укажите срок кредита в месяцах'),
    )

    class Meta:
        model = Loan
        fields = [
            'date',
            'type_loan',
            'loan_amount',
            'annual_interest_rate',
            'period_loan',
        ]
        widgets = {
            'date': DateTimeInput(
                attrs={'type': 'datetime-local', 'class': 'form-control'},
            ),
        }

    def __init__(self, *args, **kwargs):
        """
        Конструктов класса инициализирующий поля формы.

        :param args:
        :param kwargs:
        """
        self.request_user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        cd = self.cleaned_data
        form = super().save(commit=False)
        loan_amount = cd.get('loan_amount')
        form.user = self.request_user
        form.account = Account.objects.create(
            user=self.request_user,
            name_account=_(f'Кредитный счёт на {loan_amount}'),
            balance=loan_amount,
            currency='RU',
        )
        form.save()


class PaymentMakeLoanForm(BaseForm):
    date = DateTimeField(
        label=_('Дата платежа'),
        widget=DateTimeInput(
            attrs={
                'type': 'datetime-local',
                'class': 'form-control',
            },
        ),
        help_text=_('Укажите дату платежа'),
    )

    account = ModelChoiceField(
        queryset=Account.objects.all(),
        label=_('Счёт списания'),
        help_text=_('Выберите счёт для списания'),
    )

    loan = ModelChoiceField(
        queryset=Loan.objects.all(),
        label=_('Кредит'),
        help_text=_('Выберите кредит для погашения'),
    )

    amount = DecimalField(
        label=_('Сумма платежа'),
        help_text=_('Введите сумму платежа'),
    )

    def __init__(self, user, *args, **kwargs):
        """
        Исключаем из выборки счетов все счета кредитов.

        :param user:
        """
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields['account'].queryset = self.get_account_queryset()
        self.fields['loan'].queryset = Loan.objects.filter(user=user)

    def get_account_queryset(self):
        accounts = Account.objects.filter(user=self.user)

        loan = Loan.objects.filter(user=self.user).values_list(
            'account',
            flat=True,
        )
        return accounts.exclude(id__in=loan)

    class Meta:
        model = PaymentMakeLoan
        fields = ['date', 'account', 'loan', 'amount']
        widgets = {
            'date': DateTimeInput(
                attrs={'type': 'datetime-local', 'class': 'form-control'},
            ),
        }
