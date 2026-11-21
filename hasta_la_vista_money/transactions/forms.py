"""Forms for the unified transactions app."""

from datetime import UTC, datetime
from datetime import date as dt_date
from typing import Any, ClassVar
from urllib.parse import urlencode

from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.forms import (
    CharField,
    DateInput,
    DateTimeField,
    DateTimeInput,
    DecimalField,
    HiddenInput,
    ModelChoiceField,
    ModelForm,
)
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.custom_mixin import (
    CategoryChoicesConfigurerMixin,
    CategoryChoicesMixin,
    FormQuerysetsMixin,
)
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)

FORM_CONTROL_CLASS = (
    'w-full rounded-xl border border-gray-300 bg-white px-3 py-2 text-sm '
    'text-gray-900 shadow-sm transition-colors duration-200 '
    'placeholder:text-gray-400 focus:border-green-500 focus:outline-none '
    'focus:ring-0 dark:border-gray-600 '
    'dark:bg-gray-700 dark:text-white dark:placeholder:text-gray-400'
)


class TransactionForm(
    CategoryChoicesConfigurerMixin,
    FormQuerysetsMixin,
    ModelForm[Transaction],
):
    """Unified form for creating and updating transactions.

    The ``type`` field is hidden by default; views set its initial value
    based on whether the user is adding an income or an expense. Form
    validation guarantees that the chosen category's type matches the
    transaction type, and rejects expenses that exceed the account balance.
    """

    type = CharField(widget=HiddenInput(), required=True)
    category = ModelChoiceField(
        queryset=Category.objects.none(),
        label=_('Категория'),
        help_text=_('Выберите категорию операции'),
    )
    account = ModelChoiceField(
        queryset=Account.objects.none(),
        label=_('Счёт'),
        help_text=_('Выберите счёт операции'),
    )
    date = DateTimeField(
        label=_('Дата и время'),
        widget=DateTimeInput(
            format=constants.HTML5_DATETIME_LOCAL_INPUT_FORMAT,
            attrs={
                'type': 'datetime-local',
                'class': FORM_CONTROL_CLASS,
                'data-flatpickr': 'true',
                'data-flatpickr-mode': 'datetime',
                'placeholder': 'ДД.ММ.ГГГГ ЧЧ:ММ',
            },
        ),
        input_formats=list(constants.HTML5_DATETIME_LOCAL_INPUT_FORMATS),
        help_text=_('Укажите дату и время операции'),
    )
    amount = DecimalField(
        label=_('Сумма'),
        help_text=_('Введите сумму'),
    )

    field = 'category'

    def __init__(
        self,
        *args: Any,
        category_queryset: QuerySet[Category] | None = None,
        account_queryset: QuerySet[Account] | None = None,
        **kwargs: Any,
    ) -> None:
        if category_queryset is not None:
            # System categories are only used by dedicated scenarios.
            category_queryset = category_queryset.filter(system_kind='')
        super().__init__(
            *args,
            category_queryset=category_queryset,
            account_queryset=account_queryset,
            **kwargs,
        )
        self.credit_card_transfer_url: str | None = None
        self.bank_day_only = self.instance.bank_calendar_date is not None
        if self.bank_day_only:
            self.fields['date'] = DateTimeField(
                label=_('Дата операции'),
                widget=DateInput(
                    format=constants.HTML5_DATE_WIRE_FORMAT,
                    attrs={
                        'type': 'date',
                        'class': FORM_CONTROL_CLASS,
                        'data-flatpickr': 'true',
                        'data-flatpickr-mode': 'date',
                        'placeholder': 'ДД.ММ.ГГГГ',
                    },
                ),
                input_formats=[constants.HTML5_DATE_WIRE_FORMAT],
                help_text=_('Укажите банковский день операции'),
            )
            self.initial['date'] = self.instance.bank_calendar_date

    def clean_date(self) -> datetime:
        """Normalize a datetime, or a bank day's technical UTC midnight."""
        date_value = self.cleaned_data.get('date')
        if not isinstance(date_value, (datetime, dt_date)):
            raise ValidationError(_('Укажите корректную дату и время'))
        if self.bank_day_only:
            return datetime.combine(
                date_value,
                datetime.min.time(),
                tzinfo=UTC,
            )
        if isinstance(date_value, datetime):
            if timezone.is_naive(date_value):
                return timezone.make_aware(date_value)
            return date_value
        return timezone.make_aware(
            datetime.combine(date_value, datetime.min.time()),
        )

    def clean(self) -> dict[str, Any]:
        """Enforce type/category consistency and balance check for expenses."""
        cleaned_data = super().clean()
        if not cleaned_data:
            return {}

        type_value = cleaned_data.get('type')
        category = cleaned_data.get('category')
        amount = cleaned_data.get('amount')
        account_form = cleaned_data.get('account')

        if category and type_value and category.type != type_value:
            raise ValidationError(
                {
                    'category': _(
                        'Тип категории не совпадает с типом операции',
                    ),
                },
            )

        if (
            type_value == TransactionType.INCOME
            and account_form is not None
            and account_form.type_account in constants.CREDIT_ACCOUNT_TYPES
        ):
            params: dict[str, Any] = {'to_account': account_form.pk}
            if amount:
                params['amount'] = str(amount)
            self.credit_card_transfer_url = (
                f'{reverse("finance_account:transfer_money")}?'
                f'{urlencode(params)}'
            )
            self.add_error('account', constants.CREDIT_CARD_INCOME_BAN)

        if (
            type_value == TransactionType.EXPENSE
            and account_form
            and amount
            and category
        ):
            account = get_object_or_404(Account, pk=account_form.pk)
            available_balance = account.balance
            if (
                self.instance.pk
                and self.instance.type == TransactionType.EXPENSE
                and self.instance.account_id == account.pk
            ):
                available_balance += self.instance.amount
            if amount > available_balance:
                self.add_error(
                    'account',
                    _(f'Недостаточно средств на счёте {account}'),
                )

        return cleaned_data

    class Meta:
        model = Transaction
        fields: ClassVar[list[str]] = [
            'type',
            'category',
            'account',
            'date',
            'amount',
        ]


class CategoryForm(
    CategoryChoicesConfigurerMixin,
    CategoryChoicesMixin,
    ModelForm[Category],
):
    """Form for creating or updating a category of a fixed type.

    Views are expected to pre-populate the hidden ``type`` field so the
    user does not have to choose between income and expense categories in
    the UI.
    """

    type = CharField(widget=HiddenInput(), required=True)
    name = CharField(
        label=_('Название категории'),
        help_text=_('Введите название категории'),
    )
    parent_category = ModelChoiceField(
        queryset=Category.objects.none(),
        label=_('Родительская категория'),
        help_text=_('Выберите родительскую категорию'),
        empty_label=_('Нет родительской категории'),
        required=False,
    )

    field = 'parent_category'

    def __init__(
        self,
        *args: Any,
        category_queryset: QuerySet[Category] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, category_queryset=category_queryset, **kwargs)

    def clean(self) -> dict[str, Any]:
        """Verify that the parent category has the same type."""
        cleaned_data = super().clean()
        if not cleaned_data:
            return {}

        parent = cleaned_data.get('parent_category')
        type_value = cleaned_data.get('type')
        if parent and type_value and parent.type != type_value:
            raise ValidationError(
                {
                    'parent_category': _(
                        'Тип родительской категории не совпадает',
                    ),
                },
            )
        return cleaned_data

    class Meta:
        model = Category
        fields: ClassVar[list[str]] = ['type', 'name', 'parent_category']
