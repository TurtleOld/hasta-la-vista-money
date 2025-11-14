from typing import Any, ClassVar

from django.forms import (
    CharField,
    DateTimeField,
    DateTimeInput,
    DecimalField,
    ModelChoiceField,
    ModelForm,
)
from django.utils.translation import gettext_lazy as _

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
    """Модельная форма отображения доходов на сайте."""

    category = ModelChoiceField(
        queryset=IncomeCategory.objects.none(),
        label=_('Категория дохода'),
        help_text=_('Выберите категорию дохода'),
    )
    account = ModelChoiceField(
        queryset=Account.objects.none(),
        label=_('Счёт списания'),
        help_text=_('Выберите на какой счёт зачислить доход'),
    )
    date = DateTimeField(
        label=_('Дата'),
        widget=DateTimeInput(
            attrs={
                'type': 'datetime-local',
                'class': 'form-control',
            },
        ),
        help_text=_('Укажите дату и время получения дохода'),
    )
    amount = DecimalField(
        label=_('Сумма пополнения'),
        help_text=_('Введите сумму пополнения'),
    )

    field = 'category'

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
        """Инициализирует queryset для поля 'parent_category'."""
        category_queryset = kwargs.pop('category_queryset', None)
        super().__init__(*args, category_queryset=category_queryset, **kwargs)

    class Meta:
        model = IncomeCategory
        fields: ClassVar[list[str]] = ['name', 'parent_category']
