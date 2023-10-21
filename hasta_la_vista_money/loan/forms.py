"""Модуль форм по кредитам."""
from django.utils.translation import gettext_lazy as _
from hasta_la_vista_money.account.models import Account
from hasta_la_vista_money.commonlogic.forms import (
    BaseForm,
    DateTimePickerWidgetForm,
)
from hasta_la_vista_money.loan.models import Loan, PaymentMakeLoan


class LoanForm(BaseForm):
    labels = {
        'date': _('Начальная дата кредита'),
        'type_loan': _('Тип кредита'),
        'loan_amount': _('Сумма кредита'),
        'annual_interest_rate': _('Годовая ставка в %'),
        'period_loan': _('Срок кредита в месяцах'),
    }

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
            'date': DateTimePickerWidgetForm,
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
            name_account=f'Кредитный счёт на {loan_amount}',
            balance=loan_amount,
            currency='RU',
        )
        form.save()


class PaymentMakeLoanForm(BaseForm):
    labels = {
        'date': _('Дата платежа'),
        'account': _('Счёт списания'),
        'loan': _('Кредит'),
        'amount': _('Сумма платежа'),
    }

    def __init__(self, user, *args, **kwargs):
        """
        Исключаем из выборки счетов все счета кредитов.

        :param user:
        """
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields['account'].queryset = self.get_account_queryset()

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
            'date': DateTimePickerWidgetForm,
        }
