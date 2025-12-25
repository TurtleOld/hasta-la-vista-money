from datetime import datetime
from typing import Any, ClassVar

from django.forms import (
    CharField,
    DateTimeField,
    DateTimeInput,
    DecimalField,
    ModelChoiceField,
    ModelForm,
)
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.custom_mixin import (
    CategoryChoicesConfigurerMixin,
    CategoryChoicesMixin,
    FormQuerysetsMixin,
)
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income, IncomeCategory


class IncomeForm(
    CategoryChoicesConfigurerMixin,
    FormQuerysetsMixin,
    ModelForm[Income],
):
    """Model form for displaying income on the site.

    Provides form fields for creating and editing income records
    with category, account, date, and amount fields.
    """

    category = ModelChoiceField(
        queryset=IncomeCategory.objects.none(),
        label=_('Категория дохода'),
        help_text=_('Выберите категорию дохода'),
    )
    account = ModelChoiceField(
        queryset=Account.objects.none(),
        label=_('Счёт пополнения'),
        help_text=_('Выберите на какой счёт зачислить доход'),
    )
    date = DateTimeField(
        label=_('Дата'),
        widget=DateTimeInput(
            format=constants.HTML5_DATETIME_LOCAL_INPUT_FORMAT,
            attrs={
                'type': 'datetime-local',
                'class': 'form-control',
            },
        ),
        input_formats=list(constants.HTML5_DATETIME_LOCAL_INPUT_FORMATS),
        help_text=_('Укажите дату и время получения дохода'),
    )
    amount = DecimalField(
        label=_('Сумма пополнения'),
        help_text=_('Введите сумму пополнения'),
    )

    field = 'category'

    def clean_date(self) -> datetime:
        date_value = self.cleaned_data.get('date')
        if (
            date_value
            and isinstance(date_value, datetime)
            and timezone.is_naive(date_value)
        ):
            return timezone.make_aware(date_value)
        return date_value

    class Meta:
        model = Income
        fields: ClassVar[list[str]] = ['category', 'account', 'date', 'amount']


class AddCategoryIncomeForm(
    CategoryChoicesConfigurerMixin,
    CategoryChoicesMixin,
    ModelForm[IncomeCategory],
):
    name = CharField(
        label=_('Название категории'),
        help_text=_('Введите название категории дохода для её создания'),
    )
    parent_category = ModelChoiceField(
        queryset=IncomeCategory.objects.none(),
        label=_('Родительская категория'),
        help_text=_(
            'Выберите родительскую категорию дохода для создаваемой категории',
        ),
        empty_label=_('Нет родительской категории'),
        required=False,
    )
    field = 'parent_category'

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize queryset for 'parent_category' field.

        Args:
            *args: Positional arguments.
            **kwargs: Keyword arguments. 'category_queryset' is extracted
                and used to configure parent category choices.
        """
        category_queryset = kwargs.pop('category_queryset', None)
        super().__init__(*args, category_queryset=category_queryset, **kwargs)

    class Meta:
        model = IncomeCategory
        fields: ClassVar[list[str]] = ['name', 'parent_category']
