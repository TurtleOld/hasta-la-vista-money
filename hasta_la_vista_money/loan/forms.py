"""Модуль форм по кредитам."""

from decimal import Decimal
from typing import Any, ClassVar

from django.db.models import QuerySet
from django.forms import (
    ChoiceField,
    DateTimeField,
    DateTimeInput,
    DecimalField,
    IntegerField,
    ModelChoiceField,
    ModelForm,
    NumberInput,
    Select,
)
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.loan.models import Loan, PaymentMakeLoan
from hasta_la_vista_money.users.models import User


class LoanForm(ModelForm[Loan]):
    date = DateTimeField(
        label=_('Дата'),
        widget=DateTimeInput(
            format=constants.HTML5_DATETIME_LOCAL_INPUT_FORMAT,
            attrs={
                'type': 'datetime-local',
                'class': 'block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm transition-colors focus:border-green-500 focus:outline-none focus:ring-2 focus:ring-green-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:focus:border-green-400 dark:focus:ring-green-400',
            },
        ),
        input_formats=list(constants.HTML5_DATETIME_LOCAL_INPUT_FORMATS),
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
        fields: ClassVar[list[str]] = [
            'date',
            'type_loan',
            'loan_amount',
            'annual_interest_rate',
            'period_loan',
        ]
        widgets: ClassVar[dict[str, Any]] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """
        Конструктов класса инициализирующий поля формы.

        :param args:
        :param kwargs:
        """
        self.request_user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        input_classes = 'block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 pr-10 text-sm text-gray-900 shadow-sm transition-colors focus:border-green-500 focus:outline-none focus:ring-2 focus:ring-green-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:focus:border-green-400 dark:focus:ring-green-400'
        select_classes = 'block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm transition-colors focus:border-green-500 focus:outline-none focus:ring-2 focus:ring-green-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:focus:border-green-400 dark:focus:ring-green-400'

        self.fields['type_loan'].widget = Select(
            attrs={'class': select_classes}
        )
        self.fields['loan_amount'].widget = NumberInput(
            attrs={'class': input_classes, 'step': '0.01'}
        )
        self.fields['annual_interest_rate'].widget = NumberInput(
            attrs={'class': input_classes, 'step': '0.01'}
        )
        self.fields['period_loan'].widget = NumberInput(
            attrs={'class': input_classes, 'step': '1'}
        )

    def save(self, commit: bool = True) -> Loan:
        cd = self.cleaned_data
        form = super().save(commit=False)
        loan_amount = cd.get('loan_amount')
        if loan_amount is None:
            raise ValueError('loan_amount is required')
        form.user = self.request_user
        form.account = Account.objects.create(
            user=self.request_user,
            name_account=str(_(f'Кредитный счёт на {loan_amount}')),
            balance=Decimal(str(loan_amount)),
            currency='RU',
            type_account=Account.TYPE_ACCOUNT_LIST[0][0],
        )
        form.save()
        return form


class PaymentMakeLoanForm(ModelForm[PaymentMakeLoan]):
    date = DateTimeField(
        label=_('Дата платежа'),
        widget=DateTimeInput(
            format=constants.HTML5_DATETIME_LOCAL_INPUT_FORMAT,
            attrs={
                'type': 'datetime-local',
                'class': 'block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm transition-colors focus:border-green-500 focus:outline-none focus:ring-2 focus:ring-green-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:focus:border-green-400 dark:focus:ring-green-400',
            },
        ),
        input_formats=list(constants.HTML5_DATETIME_LOCAL_INPUT_FORMATS),
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

    def __init__(
        self,
        user: User,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """
        Исключаем из выборки счетов все счета кредитов.

        :param user:
        """
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields['account'].queryset = self.get_account_queryset()  # type: ignore[attr-defined]
        self.fields['loan'].queryset = Loan.objects.filter(user=user)  # type: ignore[attr-defined]

        input_classes = 'block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 pr-10 text-sm text-gray-900 shadow-sm transition-colors focus:border-green-500 focus:outline-none focus:ring-2 focus:ring-green-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:focus:border-green-400 dark:focus:ring-green-400'
        select_classes = 'block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm transition-colors focus:border-green-500 focus:outline-none focus:ring-2 focus:ring-green-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:focus:border-green-400 dark:focus:ring-green-400'

        self.fields['account'].widget.attrs.update({'class': select_classes})
        self.fields['loan'].widget.attrs.update({'class': select_classes})
        self.fields['amount'].widget = NumberInput(
            attrs={'class': input_classes, 'step': '0.01'}
        )

    def get_account_queryset(self) -> QuerySet[Account]:
        accounts = Account.objects.filter(user=self.user)

        loan = Loan.objects.filter(user=self.user).values_list(
            'account',
            flat=True,
        )
        return accounts.exclude(id__in=loan)

    class Meta:
        model = PaymentMakeLoan
        fields: ClassVar[list[str]] = [
            'date',
            'account',
            'loan',
            'amount',
        ]
        widgets: ClassVar[dict[str, Any]] = {}
