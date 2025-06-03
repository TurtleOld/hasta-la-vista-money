from django.forms import (
    DateTimeInput,
    ModelChoiceField,
    DateTimeField,
    DecimalField,
    CharField,
)
from django.utils.translation import gettext_lazy as _
from hasta_la_vista_money.commonlogic.forms import BaseForm
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income, IncomeCategory


class IncomeForm(BaseForm):
    """Модельная форма отображения доходов на сайте."""

    category = ModelChoiceField(
        queryset=IncomeCategory.objects.all(),
        label=_('Категория дохода'),
        help_text=_('Выберите категорию дохода'),
    )
    account = ModelChoiceField(
        queryset=Account.objects.all(),
        label=_('Счёт списания'),
        help_text=_('Выберите на какой счёт зачислить доход'),
    )
    date = DateTimeField(
        label=_('Дата'),
        widget=DateTimeInput(
            attrs={
                'type': 'datetime-local',
                'class': 'form-control',
            }
        ),
        help_text=_('Укажите дату и время получения дохода'),
    )
    amount = DecimalField(
        label=_('Сумма пополнения'),
        help_text=_('Введите сумму пополнения'),
    )

    field = 'category'

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


class AddCategoryIncomeForm(BaseForm):
    name = CharField(
        label=_('Название категории'),
        help_text=_('Введите название категории дохода для её создания'),
    )
    parent_category = ModelChoiceField(
        queryset=IncomeCategory.objects.all(),
        label=_('Родительская категория'),
        help_text=_('Выберите родительскую категорию дохода для создаваемой категории'),
    )
    field = 'parent_category'

    class Meta:
        model = IncomeCategory
        fields = ['name', 'parent_category']

    def configure_category_choices(self, category_choices):
        self.fields[self.field].choices = category_choices
