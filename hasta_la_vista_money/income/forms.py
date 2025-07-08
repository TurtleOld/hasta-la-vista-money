from django.forms import (
    CharField,
    DateTimeField,
    DateTimeInput,
    DecimalField,
    ModelChoiceField,
    ModelForm,
)
from django.utils.translation import gettext_lazy as _
from hasta_la_vista_money.custom_mixin import CategoryChoicesMixin
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income, IncomeCategory


class IncomeForm(ModelForm):
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

    def __init__(self, *args, **kwargs):
        category_queryset = kwargs.pop('category_queryset', None)
        account_queryset = kwargs.pop('account_queryset', None)
        super().__init__(*args, **kwargs)

        if category_queryset is not None:
            self.fields['category'].queryset = category_queryset
        if account_queryset is not None:
            self.fields['account'].queryset = account_queryset

    def configure_category_choices(self, category_choices):
        self.fields[self.field].choices = category_choices

    class Meta:
        model = Income
        fields = ['category', 'account', 'date', 'amount']
        widgets = {
            'date': DateTimeInput(
                attrs={'type': 'datetime-local', 'class': 'form-control'},
            ),
        }


class AddCategoryIncomeForm(CategoryChoicesMixin, ModelForm):
    name = CharField(
        label=_('Название категории'),
        help_text=_('Введите название категории дохода для её создания'),
    )
    parent_category = ModelChoiceField(
        queryset=IncomeCategory.objects.none(),
        label=_('Родительская категория'),
        help_text=_('Выберите родительскую категорию дохода для создаваемой категории'),
        empty_label=_('Нет родительской категории'),
        required=False,
    )
    field = 'parent_category'

    def __init__(self, *args, **kwargs):
        category_queryset = kwargs.pop('category_queryset', None)
        super().__init__(*args, **kwargs)

        if category_queryset is not None:
            self.fields['parent_category'].queryset = category_queryset

    class Meta:
        model = IncomeCategory
        fields = ['name', 'parent_category']

    def configure_category_choices(self, category_choices):
        self.fields[self.field].choices = category_choices
